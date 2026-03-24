import os
import logging
from typing import List, Dict, Any, TypedDict
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from langgraph.graph import StateGraph, END

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

# ==========================================
# 1. State and Data Models
# ==========================================
class AgentState(TypedDict):
    question: str
    metadata_filter: dict
    target_db: str  # 'local', 'global', or 'both'
    context: List[Document]
    answer: str
    retries: int
    is_hallucination: bool

class CritiqueOutput(BaseModel):
    is_hallucination: bool = Field(description="True if hallucinated, False if perfectly grounded.")

class RouterOutput(BaseModel):
    target_db: str = Field(description="Must be 'local', 'global', or 'both'.")

# ==========================================
# 2. The Agent Class
# ==========================================
class SecureDocAgent:
    def __init__(self, db_dir: str = "vector_db", global_db_dir: str = "global_vector_db"):
        self.db_dir = db_dir
        self.global_db_dir = global_db_dir
        self.max_retries = 2
        
        logger.info("Initializing Agentic components...")
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        
        # Initialize Local DB
        if not os.path.exists(self.db_dir):
            os.makedirs(self.db_dir, exist_ok=True)
        self.local_vectorstore = Chroma(persist_directory=self.db_dir, embedding_function=self.embeddings)
        
        # Initialize Global DB
        if not os.path.exists(self.global_db_dir):
            os.makedirs(self.global_db_dir, exist_ok=True)
        self.global_vectorstore = Chroma(persist_directory=self.global_db_dir, embedding_function=self.embeddings)
        
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        self.eval_llm = self.llm.with_structured_output(CritiqueOutput)
        self.router_llm = self.llm.with_structured_output(RouterOutput)

        self.workflow = self._build_graph()

    # --- NODE FUNCTIONS ---
    def route_query_node(self, state: AgentState):
        """Determines which database to query."""
        logger.info("NODE: Routing query...")
        prompt = ChatPromptTemplate.from_messages([
            ("system", "Analyze the query. If it asks about specific uploaded files/contracts, output 'local'. If it asks about general law/RBI/GST, output 'global'. If it requires comparing a contract to law, output 'both'."),
            ("human", "{question}")
        ])
        decision = (prompt | self.router_llm).invoke({"question": state["question"]})
        return {"target_db": decision.target_db}

    def retrieve_node(self, state: AgentState):
        """Retrieves documents from the appropriate vectorstore."""
        logger.info("NODE: Retrieving context...")
        question = state["question"]
        filters = state.get("metadata_filter")
        target = state.get("target_db", "local")
        
        # PROPER FIX: ChromaDB requires explicitly None if empty, not {}
        valid_filter = filters if filters else None

        docs = []
        if target in ["local", "both"]:
            try:
                docs.extend(self.local_vectorstore.similarity_search(query=question, k=5, filter=valid_filter))
            except Exception as e:
                logger.error(f"Local retrieval failed: {e}")
                
        if target in ["global", "both"]:
            try:
                # We don't apply user metadata filters to the global regulation DB
                docs.extend(self.global_vectorstore.similarity_search(query=question, k=3))
            except Exception as e:
                logger.error(f"Global retrieval failed: {e}")

        return {"context": docs}

    def generate_node(self, state: AgentState):
        logger.info(f"NODE: Generating answer (Attempt {state.get('retries', 0) + 1})...")
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an expert CA assistant specializing in Indian taxation and compliance. "
             "You know the Income Tax Act 1961, CGST Act 2017, Companies Act 2013, and ICAI standards.\n\n"
             "RULES:\n"
             "1. When referencing sections, always cite the exact section number and sub-section.\n"
             "2. When a client document is in context, analyze it against applicable rules and flag issues proactively.\n"
             "3. Answer in professional CA language. Amounts in Indian format (Rs. lakhs, crores). Dates in DD/MM/YYYY.\n"
             "4. Synthesize information from ALL provided context to give a comprehensive answer.\n"
             "5. When discussing violations or compliance findings, clearly state what was found and any recommended remediation.\n"
             "6. Cite specific details from the context (page numbers, values, clause references).\n"
             "7. If the context genuinely contains no relevant information, say so briefly."),
            ("human", "Context:\n{context}\n\nQuestion: {question}")
        ])
        
        formatted_context = "\n\n".join([f"[Page {doc.metadata.get('page', 'Unknown')}] {doc.page_content}" for doc in state.get("context", [])])
        response = (prompt | self.llm).invoke({"context": formatted_context, "question": state["question"]})
        
        return {"answer": response.content, "retries": state.get("retries", 0) + 1}

    def evaluate_node(self, state: AgentState):
        logger.info("NODE: Evaluating generated answer for hallucinations...")
        prompt = ChatPromptTemplate.from_messages([
            ("system", 
             "Read the Context and the Answer carefully. "
             "Mark hallucination as True ONLY if the Answer contains specific facts, numbers, or claims that are clearly fabricated and NOT derivable from the Context. "
             "Summarizing, paraphrasing, or synthesizing information that IS in the Context is NOT hallucination. "
             "If the Answer reasonably reflects the Context content, mark hallucination as False."),
            ("human", "Context: {context}\n\nAnswer: {answer}")
        ])
        
        formatted_context = "\n".join([doc.page_content for doc in state.get("context", [])])
        critique = (prompt | self.eval_llm).invoke({"context": formatted_context, "answer": state["answer"]})
        
        return {"is_hallucination": critique.is_hallucination}

    def fallback_node(self, state: AgentState):
        return {"answer": "After reviewing the documents, I cannot provide a completely verified answer to this question based solely on the text provided."}

    # --- GRAPH ROUTING & COMPILATION ---
    def route_evaluation(self, state: AgentState):
        if not state["is_hallucination"]:
            return END
        elif state["retries"] >= self.max_retries:
            return "fallback"
        else:
            return "generate"

    def _build_graph(self):
        workflow = StateGraph(AgentState)
        
        workflow.add_node("route", self.route_query_node)
        workflow.add_node("retrieve", self.retrieve_node)
        workflow.add_node("generate", self.generate_node)
        workflow.add_node("evaluate", self.evaluate_node)
        workflow.add_node("fallback", self.fallback_node)
        
        workflow.set_entry_point("route")
        workflow.add_edge("route", "retrieve")
        workflow.add_edge("retrieve", "generate")
        workflow.add_edge("generate", "evaluate")
        
        workflow.add_conditional_edges(
            "evaluate",
            self.route_evaluation,
            {END: END, "generate": "generate", "fallback": "fallback"}
        )
        workflow.add_edge("fallback", END)
        
        return workflow.compile()

    def query(self, question: str, metadata_filter: dict = None) -> dict:
        """The public entrypoint."""
        initial_state = {
            "question": question,
            "metadata_filter": metadata_filter, # Passed directly, no `or {}`
            "retries": 0
        }
        
        final_state = self.workflow.invoke(initial_state)
        
        citations = []
        for doc in final_state.get("context", []):
            source = doc.metadata.get("source", "Unknown")
            page = doc.metadata.get("page", "Unknown")
            citation = f"{source} (Page {page})"
            if citation not in citations:
                citations.append(citation)
                
        return {
            "answer": final_state.get("answer", "System Error"),
            "citations": citations
        }

    def extract_for_audit(self, focus_query: str, rule: str, metadata_filter: dict = None) -> str:
        """Direct extraction for compliance audits — bypasses the full RAG pipeline.
        
        Unlike query(), this method:
        - Skips the router (always uses local DB)
        - Skips hallucination checking
        - Uses a focused extraction prompt that always returns document content
        - Returns raw extracted text for the auditor to evaluate
        """
        logger.info(f"AUDIT EXTRACT: '{focus_query[:60]}...'")
        
        valid_filter = metadata_filter if metadata_filter else None
        
        # 1. Direct vector retrieval — increased k to capture full context (invoices are often 1-2 pages completely covered by 15 chunks)
        try:
            total_docs = self.local_vectorstore._collection.count()
            k = min(15, total_docs) if total_docs > 0 else 1
            docs = self.local_vectorstore.similarity_search(
                query=focus_query, k=k, filter=valid_filter
            )
            logger.info(f"VALIDATION (STEP 3): Retrieved {len(docs)} chunks for rule evaluation from {valid_filter}")
            
            # Additional debug logging to verify chunks used
            for i, d in enumerate(docs):
                logger.debug(f"Retrieved Chunk {i+1} [Page {d.metadata.get('page', '?')}]: {d.page_content[:100]}...")
                
        except Exception as e:
            logger.error(f"Vector retrieval failed: {e}")
            return "Extraction System Error: Vector retrieval failed."
        
        if not docs:
            logger.warning(f"VALIDATION (STEP 3): No chunks retrieved for query: '{focus_query}'")
            return "No document content was found in the database for this query."
        
        # 2. Combine all retrieved text
        combined_text = "\n\n".join([
            f"[Page {doc.metadata.get('page', '?')}]: {doc.page_content}" 
            for doc in docs
        ])
        
        # 3. Focused extraction prompt — optimized for accuracy and preventing false negatives
        extraction_prompt = ChatPromptTemplate.from_messages([
            ("system", 
             "You are an expert document extraction specialist for legal and financial compliance audits. "
             "Your job is to meticulously extract facts, values, and clauses from the provided document text that are relevant to the requested rule.\n\n"
             "CRITICAL RULES:\n"
             "1. EXTRACT EXACT FACTS: Quote specific values, numbers, dates, names, GSTINs, and clauses present in the text.\n"
             "2. DO NOT ASSUME: Only report what is actually written in the 'DOCUMENT TEXT'.\n"
             "3. BE COMPREHENSIVE: If the rule asks for multiple fields (e.g., date, supplier, GSTIN, amounts), carefully check and extract each one.\n"
             "4. IDENTIFY MISSING ELEMENTS: If a specific element required by the rule is entirely absent from the text, explicitly state that it is missing.\n"
             "5. STRICT FORMATTING: Organize your extraction clearly so the auditor can easily read the facts."),
            ("human", 
             "DOCUMENT TEXT:\n{context}\n\n"
             "EXTRACTION FOCUS: {focus}\n\n"
             "COMPLIANCE RULE BEING CHECKED: {rule}\n\n"
             "Please extract all relevant information from the text to verify this rule. List what is present and explicitly note if any strongly required elements are missing.")
        ])
        
        try:
            response = (extraction_prompt | self.llm).invoke({
                "context": combined_text,
                "focus": focus_query,
                "rule": rule
            })
            return response.content
        except Exception as e:
            logger.error(f"Extraction LLM call failed: {e}")
            return f"Extraction System Error: {str(e)}"

    def extract_structured_fields(self, blueprint_dict: dict, metadata_filter: dict = None, data_dir: str = None) -> dict:
        """
        4-STAGE EXTRACTION ARCHITECTURE:
        Stage 1 — Pure Extraction: Retrieve document text (ChromaDB → PDF fallback)
        Stage 2 — Verification: Sanity check that we actually have text
        Stage 3 — Mapping: LLM extracts structured JSON fields from raw text
        Returns empty dict ONLY if the document is truly unreadable.
        """
        import json
        import pymupdf
        from pathlib import Path
        
        logger.info(f"AUDIT EXTRACT: Processing structured JSON extraction for {len(blueprint_dict.get('checks', []))} checks")
        
        valid_filter = metadata_filter if metadata_filter else None
        combined_text = ""
        
        # =====================================================
        # STAGE 1 — PURE EXTRACTION (Two-Tier Retrieval)
        # =====================================================
        
        # TIER 1: Try ChromaDB vector store
        try:
            total_docs = self.local_vectorstore._collection.count()
            k = min(30, total_docs) if total_docs > 0 else 1
            docs = self.local_vectorstore.similarity_search(
                query="document invoice facts terms amounts dates", k=k, filter=valid_filter
            )
            logger.info(f"STAGE 1 [Tier 1 - ChromaDB]: Retrieved {len(docs)} chunks (filter: {valid_filter})")
            
            if docs:
                # Filter out previously injected audit reports to avoid poisoning extraction
                docs = [doc for doc in docs if doc.metadata.get("type") != "audit_report"]
                combined_text = "\n\n".join([
                    f"[Page {doc.metadata.get('page', '?')}]: {doc.page_content}"
                    for doc in docs
                ])
        except Exception as e:
            logger.warning(f"STAGE 1 [Tier 1 - ChromaDB]: Vector retrieval failed: {e}")
        
        # TIER 2: If ChromaDB returned nothing, read the PDF directly from disk
        if not combined_text:
            source_filename = valid_filter.get("source") if valid_filter else None
            logger.warning(f"STAGE 1 [Tier 2 - Direct PDF]: ChromaDB returned 0 chunks. Attempting direct PDF read for '{source_filename}'")
            
            if source_filename and data_dir:
                pdf_path = Path(data_dir).resolve() / source_filename
                if pdf_path.exists():
                    try:
                        doc = pymupdf.open(pdf_path)
                        pages_text = []
                        try:
                            for page_num in range(len(doc)):
                                page = doc.load_page(page_num)
                                text = page.get_text("text").strip()

                                # OCR fallback for scanned pages
                                if not text:
                                    try:
                                        import pdfplumber
                                        with pdfplumber.open(pdf_path) as pl_doc:
                                            pl_page = pl_doc.pages[page_num]
                                            extracted = pl_page.extract_text()
                                            if extracted:
                                                text = extracted.strip()

                                            # Also try extracting tables
                                            tables = pl_page.extract_tables()
                                            if tables:
                                                table_text = "\n".join([" | ".join([cell if cell else "" for cell in row]) for table in tables for row in table])
                                                text += "\n" + table_text
                                    except Exception:
                                        pass

                                if not text:
                                    try:
                                        from PIL import Image
                                        import pytesseract
                                        zoom_matrix = pymupdf.Matrix(2, 2)
                                        pix = page.get_pixmap(matrix=zoom_matrix)
                                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                                        text = pytesseract.image_to_string(img).strip()
                                    except Exception:
                                        pass

                                if text:
                                    pages_text.append(f"[Page {page_num + 1}]: {text}")
                        finally:
                            doc.close()
                        combined_text = "\n\n".join(pages_text)
                        logger.info(f"STAGE 1 [Tier 2 - Direct PDF]: Extracted {len(combined_text)} characters from {source_filename}")
                    except Exception as e:
                        logger.error(f"STAGE 1 [Tier 2 - Direct PDF]: Failed to read {pdf_path}: {e}")
                else:
                    logger.error(f"STAGE 1 [Tier 2 - Direct PDF]: File not found at {pdf_path}")
            
            # TIER 2b: If no source_filename filter, try ALL documents in ChromaDB without filter
            if not combined_text:
                try:
                    docs = self.local_vectorstore.similarity_search(
                        query="document invoice facts terms", k=30, filter=None
                    )
                    if docs:
                        combined_text = "\n\n".join([doc.page_content for doc in docs])
                        logger.info(f"STAGE 1 [Tier 2b - Unfiltered]: Retrieved {len(docs)} chunks without filter")
                except Exception:
                    pass
        
        # =====================================================
        # STAGE 2 — VERIFICATION GATE (Sanity Check)
        # =====================================================
        if not combined_text or len(combined_text.strip()) < 20:
            logger.error("STAGE 2 [Verification]: FAILED — No readable text found in document after all retrieval tiers.")
            return {}  # Truly unreadable document
        
        logger.info(f"STAGE 2 [Verification]: PASSED — {len(combined_text)} chars of document text available for extraction.")
        
        # =====================================================
        # STAGE 3 — FRAMEWORK-AGNOSTIC MAPPING (LLM Extraction)
        # =====================================================
        json_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind(response_format={"type": "json_object"})
        
        extraction_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an expert document data extraction specialist.\n\n"
             "Your task: Read the DOCUMENT TEXT below and extract ALL facts, values, and data points "
             "into a structured JSON object.\n\n"
             "CRITICAL RULES:\n"
             "1. OUTPUT VALID JSON ONLY.\n"
             "2. READ THE DOCUMENT CAREFULLY. The text contains real data — extract it precisely.\n"
             "3. The COMPLIANCE BLUEPRINT below lists checks with 'focus' and 'rule' fields. "
             "   For EACH check, extract the specific data points needed to evaluate that rule.\n"
             "4. Use the check_id as a top-level key, with nested fields for the extracted values.\n"
             "5. ALSO extract any general document metadata you find: "
             "   supplier_name, gstin, invoice_number, dates, amounts, tax rates, HSN/SAC codes, "
             "   payment terms, etc. — under a key called 'document_metadata'.\n"
             "6. EXACT VALUES: Copy values exactly as they appear in the text.\n"
             "7. MISSING DATA: Set a field to null ONLY if you have carefully searched the entire "
             "   document text and the information is genuinely not present.\n"
             "8. NEVER return an empty object when the document clearly contains data.\n"
             "9. Include a special field '_raw_text_length' with the character count of the document text "
             "   you received."),
            ("human",
             "DOCUMENT TEXT:\n{context}\n\n"
             "COMPLIANCE BLUEPRINT (extract data needed to evaluate each check):\n{blueprint}\n\n"
             "Extract and return the structured JSON object now.")
        ])
        
        try:
            response = (extraction_prompt | json_llm).invoke({
                "context": combined_text,
                "blueprint": json.dumps(blueprint_dict, indent=2)
            })
            structured_data = json.loads(response.content)
            
            # Stage 2b: Post-extraction sanity check
            raw_len = structured_data.pop("_raw_text_length", 0)

            def _count_non_null(obj):
                if isinstance(obj, dict):
                    return sum(_count_non_null(v) for v in obj.values())
                if isinstance(obj, list):
                    return sum(_count_non_null(v) for v in obj)
                return 0 if obj is None else 1

            non_null_count = _count_non_null(structured_data)
            
            # --- DEBUG LOGGING ---
            logger.info("=== DEBUG: EXTRACTED DOCUMENT TEXT ===")
            logger.info(combined_text[:1000] + ("..." if len(combined_text) > 1000 else ""))
            logger.info("=== DEBUG: EXTRACTED INVOICE FIELDS ===")
            logger.info(json.dumps(structured_data, indent=2))
            logger.info("=======================================")
            
            logger.info(f"STAGE 3 [Mapping]: Extracted {len(structured_data)} fields ({non_null_count} non-null). LLM saw {raw_len} chars.")
            
            # If the LLM returned all nulls but we KNOW text was present, log a warning and mark as failure
            if non_null_count == 0:
                logger.error("STAGE 3 [Mapping]: ERROR — LLM returned 0 actual fields. Rejecting extraction to trigger SYSTEM_ERROR.")
                return {}
            
            return structured_data
        except Exception as e:
            logger.error(f"STAGE 3 [Mapping]: LLM extraction or JSON parsing failed: {e}")
            return {}

    def extract_notice_fields(self, blueprint_dict: dict, metadata_filter: dict = None, data_dir: str = None) -> dict:
        """
        Notice-specific extraction pipeline. Reuses Stage 1 (ChromaDB → PDF fallback)
        and Stage 2 (verification gate) from extract_structured_fields, but uses a
        notice-tailored Stage 3 prompt for better legal document extraction.
        """
        import json
        import pymupdf
        from pathlib import Path

        logger.info(f"NOTICE EXTRACT: Processing {len(blueprint_dict.get('checks', []))} checks")

        valid_filter = metadata_filter if metadata_filter else None
        combined_text = ""

        # =====================================================
        # STAGE 1 — PURE EXTRACTION (same as extract_structured_fields)
        # =====================================================

        # TIER 1: ChromaDB vector store
        try:
            total_docs = self.local_vectorstore._collection.count()
            k = min(30, total_docs) if total_docs > 0 else 1
            docs = self.local_vectorstore.similarity_search(
                query="notice section assessment year demand amount penalty tax period deadline", k=k, filter=valid_filter
            )
            logger.info(f"NOTICE STAGE 1 [Tier 1 - ChromaDB]: Retrieved {len(docs)} chunks (filter: {valid_filter})")

            if docs:
                docs = [doc for doc in docs if doc.metadata.get("type") != "audit_report"]
                combined_text = "\n\n".join([
                    f"[Page {doc.metadata.get('page', '?')}]: {doc.page_content}"
                    for doc in docs
                ])
        except Exception as e:
            logger.warning(f"NOTICE STAGE 1 [Tier 1 - ChromaDB]: Vector retrieval failed: {e}")

        # TIER 2: Direct PDF read fallback
        if not combined_text:
            source_filename = valid_filter.get("source") if valid_filter else None
            logger.warning(f"NOTICE STAGE 1 [Tier 2 - Direct PDF]: Attempting direct read for '{source_filename}'")

            if source_filename and data_dir:
                pdf_path = Path(data_dir).resolve() / source_filename
                if pdf_path.exists():
                    try:
                        doc = pymupdf.open(pdf_path)
                        pages_text = []
                        try:
                            for page_num in range(len(doc)):
                                page = doc.load_page(page_num)
                                text = page.get_text("text").strip()

                                if not text:
                                    try:
                                        import pdfplumber
                                        with pdfplumber.open(pdf_path) as pl_doc:
                                            pl_page = pl_doc.pages[page_num]
                                            extracted = pl_page.extract_text()
                                            if extracted:
                                                text = extracted.strip()
                                            tables = pl_page.extract_tables()
                                            if tables:
                                                table_text = "\n".join([" | ".join([cell if cell else "" for cell in row]) for table in tables for row in table])
                                                text += "\n" + table_text
                                    except Exception:
                                        pass

                                if not text:
                                    try:
                                        from PIL import Image
                                        import pytesseract
                                        zoom_matrix = pymupdf.Matrix(2, 2)
                                        pix = page.get_pixmap(matrix=zoom_matrix)
                                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                                        text = pytesseract.image_to_string(img).strip()
                                    except Exception:
                                        pass

                                if text:
                                    pages_text.append(f"[Page {page_num + 1}]: {text}")
                        finally:
                            doc.close()
                        combined_text = "\n\n".join(pages_text)
                        logger.info(f"NOTICE STAGE 1 [Tier 2]: Extracted {len(combined_text)} chars from {source_filename}")
                    except Exception as e:
                        logger.error(f"NOTICE STAGE 1 [Tier 2]: Failed to read {pdf_path}: {e}")

            # TIER 2b: Unfiltered ChromaDB
            if not combined_text:
                try:
                    docs = self.local_vectorstore.similarity_search(
                        query="notice section assessment year demand amount", k=30, filter=None
                    )
                    if docs:
                        combined_text = "\n\n".join([doc.page_content for doc in docs])
                        logger.info(f"NOTICE STAGE 1 [Tier 2b]: Retrieved {len(docs)} chunks without filter")
                except Exception:
                    pass

        # =====================================================
        # STAGE 2 — VERIFICATION GATE
        # =====================================================
        if not combined_text or len(combined_text.strip()) < 20:
            logger.error("NOTICE STAGE 2 [Verification]: FAILED — No readable text found.")
            return {}

        logger.info(f"NOTICE STAGE 2 [Verification]: PASSED — {len(combined_text)} chars available.")

        # =====================================================
        # STAGE 3 — NOTICE-SPECIFIC EXTRACTION
        # =====================================================
        json_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).bind(response_format={"type": "json_object"})

        # Build per-check format instructions from blueprint
        checks = blueprint_dict.get("checks", [])
        checks_formatted_parts = []
        for check in checks:
            check_id = check.get("check_id", "unknown")
            focus = check.get("focus", "")
            rule = check.get("rule", "")
            checks_formatted_parts.append(
                f'  "{check_id}": {{...}}  // Focus: {focus}. Rule: {rule}'
            )
        checks_formatted = "\n".join(checks_formatted_parts)

        notice_extraction_prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an expert Indian tax notice analyst.\n\n"
             "TASK: Read the NOTICE TEXT and extract ALL key information into structured JSON.\n\n"
             "REQUIRED OUTPUT STRUCTURE:\n"
             "{{\n"
             '  "notice_summary": {{\n'
             '    "notice_date": "...",\n'
             '    "issuing_authority": "...",\n'
             '    "section_number": "...",\n'
             '    "assessment_year_or_tax_period": "...",\n'
             '    "response_deadline": "...",\n'
             '    "demand_amount": "...",\n'
             '    "taxpayer_name": "...",\n'
             '    "taxpayer_pan_or_gstin": "...",\n'
             '    "notice_reference_number": "..."\n'
             "  }},\n"
             "{checks_formatted}\n"
             "}}\n\n"
             "RULES:\n"
             "1. OUTPUT VALID JSON ONLY.\n"
             "2. Copy values EXACTLY as they appear in the notice.\n"
             "3. For each check_id, extract the specific information described in its focus/rule.\n"
             "4. Use null ONLY if information is genuinely absent from the notice.\n"
             '5. Include "_raw_text_length" with the character count of notice text received.\n'
             "6. IMPORTANT for demand_amount in notice_summary: Use the ACTUAL demand/tax payable amount computed by the authority, NOT the net refund/payable after adjustments. "
             "In 143(1) intimations, prefer 'Tax Determined' or 'Demand' amount over 'Net Amount Payable/Refundable' which may be zero after TDS credit."),
            ("human",
             "NOTICE TEXT:\n{context}\n\n"
             "Extract and return the structured JSON object now.")
        ])

        try:
            response = (notice_extraction_prompt | json_llm).invoke({
                "context": combined_text,
                "checks_formatted": checks_formatted,
            })
            structured_data = json.loads(response.content)

            raw_len = structured_data.pop("_raw_text_length", 0)

            def _count_non_null(obj):
                if isinstance(obj, dict):
                    return sum(_count_non_null(v) for v in obj.values())
                if isinstance(obj, list):
                    return sum(_count_non_null(v) for v in obj)
                return 0 if obj is None else 1

            non_null_count = _count_non_null(structured_data)

            logger.info(f"NOTICE STAGE 3 [Mapping]: Extracted {len(structured_data)} fields ({non_null_count} non-null). LLM saw {raw_len} chars.")

            if non_null_count == 0:
                logger.error("NOTICE STAGE 3 [Mapping]: LLM returned 0 actual fields.")
                return {}

            return structured_data
        except Exception as e:
            logger.error(f"NOTICE STAGE 3 [Mapping]: Failed: {e}")
            return {}

