"""Layer 1 — Blueprint-agnostic full document parsing using Gemini 2.5 Pro."""

import json
import logging
import re

from langchain_core.prompts import ChatPromptTemplate

from services.llm_config import get_json_llm

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 200_000  # Gemini 2.5 Pro supports ~1M tokens; raised from 24K
RETRY_INPUT_CHARS = 100_000


def _robust_json_parse(text: str) -> dict:
    """Try multiple strategies to extract valid JSON from LLM output."""
    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Strip markdown code fences
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        stripped = "\n".join(lines)
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    # Strategy 3: Extract substring between first { and last }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        substring = text[start:end + 1]
        try:
            return json.loads(substring)
        except json.JSONDecodeError:
            pass

        # Strategy 4: Regex cleanup on the substring (trailing commas, unescaped newlines)
        cleaned = re.sub(r',\s*([}\]])', r'\1', substring)  # trailing commas
        cleaned = cleaned.replace('\n', '\\n')  # unescaped newlines inside strings
        # But we need real newlines between JSON keys, so restore them outside quotes
        # Simpler: just try replacing literal newlines
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    return {}


class DocumentParser:
    """Extracts ALL structured data from a document in one pass.

    Unlike the old extract_structured_fields(), this is blueprint-agnostic:
    it extracts everything (tables, headers, metadata, amounts) so the same
    parsed output can serve multiple blueprints.
    """

    def __init__(self):
        self.llm = get_json_llm(heavy=True, max_tokens=8192)

    def parse_document(self, combined_text: str) -> dict:
        """Extract ALL data from document text into structured JSON.

        Returns a dict with keys like:
        - company_info: {name, gstin, pan, address, ...}
        - document_metadata: {type, number, date, period, ...}
        - parties: [{name, gstin, address, ...}, ...]
        - line_items: [{description, hsn_sac, qty, rate, amount, tax_rate, ...}, ...]
        - tables: [{header: [...], rows: [[...], ...]}, ...]
        - sections: [{heading, content}, ...]
        - totals: {subtotal, cgst, sgst, igst, cess, total, ...}
        - other_fields: {...}  — anything else found
        """
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an expert document data extraction specialist.\n\n"
             "TASK: Read the entire document text and extract ALL data into a structured JSON object.\n\n"
             "RULES:\n"
             "1. OUTPUT VALID JSON ONLY — no markdown, no explanations.\n"
             "2. TABLES: Convert every table into an array of objects with column headers as keys.\n"
             "3. SECTIONS: Capture every section heading and its content.\n"
             "4. HEADER/FOOTER: Extract all fields (company name, GSTIN, PAN, invoice number, dates, etc.).\n"
             "5. AMOUNTS: Extract all monetary values with their labels. Use numeric values where possible.\n"
             "6. TAX DETAILS: Extract tax rates, HSN/SAC codes, taxable values, CGST/SGST/IGST amounts.\n"
             "7. PARTIES: Extract supplier/buyer/payer/deductee details separately.\n"
             "8. Use null for genuinely missing fields — NEVER omit keys you looked for.\n"
             "9. NEVER return an empty object if the document contains readable data.\n"
             "10. Include '_raw_text_length' with the character count of the input text.\n\n"
             "STRUCTURE your output as:\n"
             "{{\n"
             '  "company_info": {{...}},\n'
             '  "document_metadata": {{type, number, date, period, ...}},\n'
             '  "parties": [{{name, gstin, address, role}}, ...],\n'
             '  "line_items": [{{description, hsn_sac, qty, rate, amount, tax_rate}}, ...],\n'
             '  "tables": [{{header: [...], rows: [[...]]}}, ...],\n'
             '  "sections": [{{heading, content}}, ...],\n'
             '  "totals": {{subtotal, cgst, sgst, igst, cess, total, ...}},\n'
             '  "other_fields": {{...}},\n'
             '  "_raw_text_length": <int>\n'
             "}}"),
            ("human",
             "DOCUMENT TEXT:\n{context}\n\n"
             "Extract and return the structured JSON object now."),
        ])

        # For very long docs, use chunked parsing; otherwise truncate
        if len(combined_text) > MAX_INPUT_CHARS:
            logger.info(f"Layer 1 [DocumentParser]: Document is {len(combined_text)} chars — using chunked parsing")
            return self.parse_document_chunked(combined_text)

        for attempt in range(2):
            try:
                response = (prompt | self.llm).invoke({"context": combined_text})
                content = response.content

                parsed = _robust_json_parse(content)
                if not parsed:
                    raise ValueError(f"All JSON parse strategies failed on {len(content)} chars")

                raw_len = parsed.pop("_raw_text_length", 0)
                logger.info(f"Layer 1 [DocumentParser]: Extracted {len(parsed)} top-level keys. "
                            f"LLM saw {raw_len} chars of document text. (attempt {attempt + 1})")
                return parsed

            except Exception as e:
                logger.warning(f"Layer 1 [DocumentParser]: Attempt {attempt + 1} failed: {e}")
                if attempt == 0:
                    # Retry with shorter input
                    combined_text = combined_text[:RETRY_INPUT_CHARS]
                    logger.info(f"Layer 1 [DocumentParser]: Retrying with {RETRY_INPUT_CHARS} chars")
                else:
                    logger.error(f"Layer 1 [DocumentParser]: All attempts exhausted")
                    return {}

    def parse_document_chunked(self, combined_text: str) -> dict:
        """Parse documents exceeding MAX_INPUT_CHARS by splitting into overlapping chunks.

        Splits text into 2 halves with 2000-char overlap, parses each independently,
        then deep-merges the results.
        """
        mid = len(combined_text) // 2
        overlap = 2000
        chunk1 = combined_text[:mid + overlap]
        chunk2 = combined_text[mid - overlap:]

        logger.info(f"Layer 1 [DocumentParser]: Chunked parsing — chunk1={len(chunk1)} chars, chunk2={len(chunk2)} chars")

        # Truncate each chunk to MAX_INPUT_CHARS for safety
        chunk1 = chunk1[:MAX_INPUT_CHARS]
        chunk2 = chunk2[:MAX_INPUT_CHARS]

        result1 = self._parse_single_chunk(chunk1)
        result2 = self._parse_single_chunk(chunk2)

        return self._deep_merge(result1, result2)

    def _parse_single_chunk(self, text: str) -> dict:
        """Parse a single chunk — same logic as parse_document but without chunked fallback."""
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an expert document data extraction specialist.\n\n"
             "TASK: Read the entire document text and extract ALL data into a structured JSON object.\n\n"
             "RULES:\n"
             "1. OUTPUT VALID JSON ONLY — no markdown, no explanations.\n"
             "2. TABLES: Convert every table into an array of objects with column headers as keys.\n"
             "3. SECTIONS: Capture every section heading and its content.\n"
             "4. HEADER/FOOTER: Extract all fields (company name, GSTIN, PAN, invoice number, dates, etc.).\n"
             "5. AMOUNTS: Extract all monetary values with their labels. Use numeric values where possible.\n"
             "6. TAX DETAILS: Extract tax rates, HSN/SAC codes, taxable values, CGST/SGST/IGST amounts.\n"
             "7. PARTIES: Extract supplier/buyer/payer/deductee details separately.\n"
             "8. Use null for genuinely missing fields — NEVER omit keys you looked for.\n"
             "9. NEVER return an empty object if the document contains readable data.\n\n"
             "STRUCTURE your output as:\n"
             "{{\n"
             '  "company_info": {{...}},\n'
             '  "document_metadata": {{type, number, date, period, ...}},\n'
             '  "parties": [{{name, gstin, address, role}}, ...],\n'
             '  "line_items": [{{description, hsn_sac, qty, rate, amount, tax_rate}}, ...],\n'
             '  "tables": [{{header: [...], rows: [[...]]}}, ...],\n'
             '  "sections": [{{heading, content}}, ...],\n'
             '  "totals": {{subtotal, cgst, sgst, igst, cess, total, ...}},\n'
             '  "other_fields": {{...}}\n'
             "}}"),
            ("human",
             "DOCUMENT TEXT:\n{context}\n\n"
             "Extract and return the structured JSON object now."),
        ])

        for attempt in range(2):
            try:
                response = (prompt | self.llm).invoke({"context": text})
                parsed = _robust_json_parse(response.content)
                if parsed:
                    parsed.pop("_raw_text_length", None)
                    return parsed
            except Exception as e:
                logger.warning(f"Layer 1 [DocumentParser chunk]: Attempt {attempt + 1} failed: {e}")
                if attempt == 0:
                    text = text[:RETRY_INPUT_CHARS]
        return {}

    @staticmethod
    def _deep_merge(base: dict, overlay: dict) -> dict:
        """Deep-merge two parsed document dicts: dicts merged, arrays concatenated, scalars prefer first non-null."""
        merged = {}
        all_keys = set(list(base.keys()) + list(overlay.keys()))
        for key in all_keys:
            v1 = base.get(key)
            v2 = overlay.get(key)
            if isinstance(v1, dict) and isinstance(v2, dict):
                merged[key] = DocumentParser._deep_merge(v1, v2)
            elif isinstance(v1, list) and isinstance(v2, list):
                # Concatenate and deduplicate by string representation
                seen = set()
                result = []
                for item in v1 + v2:
                    item_key = json.dumps(item, sort_keys=True, default=str) if isinstance(item, (dict, list)) else str(item)
                    if item_key not in seen:
                        seen.add(item_key)
                        result.append(item)
                merged[key] = result
            elif v1 is not None:
                merged[key] = v1
            else:
                merged[key] = v2
        return merged
