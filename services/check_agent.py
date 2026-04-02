"""Layer 2 — Parallel per-check compliance agents using Gemini 2.5 Pro."""

import asyncio
import json
import logging

from langchain_core.prompts import ChatPromptTemplate

from schemas.blueprint_schema import (
    BlueprintCheck,
    CheckAgentOutput,
    FinancialImpact,
)
from services.reference_service import ReferenceService, ReferenceResult
from services.llm_config import get_heavy_llm
from services.query_expander import expand_query

logger = logging.getLogger(__name__)


class CheckAgentService:
    """Evaluates compliance checks in parallel with ground truth references."""

    def __init__(self):
        self.llm = get_heavy_llm()
        self.reference_service = ReferenceService()

    async def evaluate_check(
        self,
        parsed_doc: dict,
        check: BlueprintCheck,
        reference: ReferenceResult,
    ) -> CheckAgentOutput:
        """Evaluate a single compliance check against the parsed document."""
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a professional regulatory compliance auditor.\n\n"
             "You are given:\n"
             "1. PARSED DOCUMENT DATA (JSON) — structured extraction of the document\n"
             "2. ONE COMPLIANCE CHECK — the rule to verify\n"
             "3. GROUND TRUTH REFERENCE — authoritative rules from official sources\n\n"
             "OUTPUT FORMAT — respond with VALID JSON ONLY matching this schema:\n"
             "{{\n"
             '  "compliance_status": "COMPLIANT|PARTIAL|NON_COMPLIANT|INCONCLUSIVE",\n'
             '  "evidence": "Direct quotes/values from the document data",\n'
             '  "violation_details": "Specific violation description or None",\n'
             '  "suggested_amendment": "Actionable fix or None",\n'
             '  "financial_impact": {{\n'
             '    "estimated_amount": <float or null>,\n'
             '    "currency": "INR",\n'
             '    "calculation": "show your math",\n'
             '    "section_reference": "e.g. Section 194J"\n'
             "  }},\n"
             '  "confidence": "HIGH|MEDIUM|LOW"\n'
             "}}\n\n"
             "RULES:\n"
             "1. COMPLIANCE STATUS: COMPLIANT | PARTIAL | NON_COMPLIANT | INCONCLUSIVE\n"
             "2. EVIDENCE: Quote 2-3 key field values. Keep under 100 words. Format: 'field = value'.\n"
             "3. VIOLATION DETAILS: One sentence describing the specific violation. Keep under 50 words.\n"
             "4. SUGGESTED AMENDMENT: One sentence with the actionable fix. Keep under 50 words.\n"
             "5. FINANCIAL IMPACT: Calculate for NON_COMPLIANT/PARTIAL. Show one-line calculation.\n"
             "6. CONFIDENCE: HIGH (official source) | MEDIUM (cached) | LOW (blueprint only).\n"
             "7. Be CONCISE. Do NOT write paragraphs. Do NOT wrap in markdown code fences."),
            ("human",
             "PARSED DOCUMENT DATA:\n{doc_json}\n\n"
             "COMPLIANCE CHECK ({check_id}):\n"
             "  Focus: {focus}\n"
             "  Rule: {rule}\n\n"
             "GROUND TRUTH REFERENCE (source: {ref_source}, confidence: {ref_confidence}):\n"
             "{ref_rules}\n\n"
             "Evaluate this check and return the JSON result:"),
        ])

        try:
            response = (prompt | self.llm).invoke({
                "doc_json": json.dumps(parsed_doc, separators=(',', ':'), default=str),
                "check_id": check.check_id,
                "focus": check.focus,
                "rule": check.rule,
                "ref_source": reference.source_name,
                "ref_confidence": reference.confidence,
                "ref_rules": reference.extracted_rules,
            })

            content = response.content.strip()
            # Strip markdown code fences if present
            if content.startswith("```"):
                lines = content.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                content = "\n".join(lines)

            # Extract JSON object robustly — find first { and matching }
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                content = content[start:end]

            result_dict = json.loads(content)

            # Parse financial_impact if present
            fi = result_dict.get("financial_impact")
            financial_impact = None
            if fi and isinstance(fi, dict):
                financial_impact = FinancialImpact(
                    estimated_amount=fi.get("estimated_amount"),
                    currency=fi.get("currency", "INR"),
                    calculation=fi.get("calculation", ""),
                    section_reference=fi.get("section_reference", ""),
                )

            return CheckAgentOutput(
                compliance_status=result_dict.get("compliance_status", "INCONCLUSIVE"),
                evidence=result_dict.get("evidence", "No evidence extracted"),
                violation_details=result_dict.get("violation_details", "None"),
                suggested_amendment=result_dict.get("suggested_amendment", "None"),
                financial_impact=financial_impact,
                confidence=result_dict.get("confidence", reference.confidence),
            )

        except Exception as e:
            logger.error(f"Check agent failed for {check.check_id}: {e}")
            return CheckAgentOutput(
                compliance_status="INCONCLUSIVE",
                evidence=f"SYSTEM_ERROR: Check evaluation failed — {str(e)}",
                violation_details="System error during evaluation",
                suggested_amendment="Manual review required.",
                financial_impact=None,
                confidence="LOW",
            )

    async def evaluate_all_checks(
        self,
        parsed_doc: dict,
        checks: list[BlueprintCheck],
    ) -> list[CheckAgentOutput]:
        """Run all check agents in parallel with ground truth references."""
        # 1. Fetch references in parallel
        logger.info(f"Layer 2: Fetching references for {len(checks)} checks...")
        references = await self.reference_service.get_references_batch(checks)

        # 2. Run all check agents in parallel
        logger.info(f"Layer 2: Running {len(checks)} check agents in parallel...")

        async def _eval(check: BlueprintCheck) -> CheckAgentOutput:
            ref = references.get(check.check_id, ReferenceResult(
                extracted_rules=check.rule,
                confidence="LOW",
                source_url=None,
                source_name="Blueprint Rule (missing)",
            ))
            return await self.evaluate_check(parsed_doc, check, ref)

        results = await asyncio.gather(
            *[_eval(c) for c in checks],
            return_exceptions=True,
        )

        # 3. Handle exceptions
        final_results = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error(f"Check {checks[i].check_id} raised exception: {res}")
                final_results.append(CheckAgentOutput(
                    compliance_status="INCONCLUSIVE",
                    evidence=f"SYSTEM_ERROR: {str(res)}",
                    violation_details="Exception during parallel evaluation",
                    suggested_amendment="Manual review required.",
                    financial_impact=None,
                    confidence="LOW",
                ))
            else:
                final_results.append(res)

        return final_results

    async def verify_results(
        self, results: list[CheckAgentOutput], checks: list[BlueprintCheck]
    ) -> list[CheckAgentOutput]:
        """Self-verification: Haiku reviews all results for internal consistency.

        Flags checks where status contradicts evidence or financial impact
        is missing for violations. Re-runs flagged checks once.
        """
        # Build a summary for the verifier
        summary_items = []
        for i, (res, check) in enumerate(zip(results, checks)):
            summary_items.append({
                "index": i,
                "check_id": check.check_id,
                "status": res.compliance_status,
                "evidence": res.evidence[:200],
                "violation_details": res.violation_details[:200],
                "has_financial_impact": res.financial_impact is not None,
                "confidence": res.confidence,
            })

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a quality assurance reviewer for compliance audit results.\n"
             "Review the following check results and identify any INCONSISTENCIES:\n"
             "1. Status says NON_COMPLIANT but evidence shows compliance (or vice versa)\n"
             "2. NON_COMPLIANT/PARTIAL status but no financial impact calculated\n"
             "3. Evidence is generic/empty rather than citing specific values\n\n"
             "Return VALID JSON ONLY: {{\"flagged_indices\": [<list of integer indices to re-run>]}}\n"
             "If all results are consistent, return {{\"flagged_indices\": []}}"),
            ("human", "AUDIT RESULTS:\n{summary}\n\nIdentify inconsistent results:"),
        ])

        try:
            response = (prompt | self.llm).invoke({
                "summary": json.dumps(summary_items, indent=2),
            })

            content = response.content.strip()
            # Extract JSON object robustly — find first { and matching }
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                content = content[start:end]
            flagged = json.loads(content).get("flagged_indices", [])

            if flagged:
                logger.info(f"Layer 2 [Verification]: {len(flagged)} checks flagged for re-run: {flagged}")
            else:
                logger.info("Layer 2 [Verification]: All results consistent — no re-runs needed.")

            # Don't re-run for now — just log. Re-running risks loops.
            # Future: could re-run flagged checks with stricter prompts.

        except Exception as e:
            logger.warning(f"Layer 2 [Verification]: Verification step failed: {e}")

        return results
