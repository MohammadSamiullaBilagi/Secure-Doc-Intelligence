import json
import logging
import asyncio
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.models.notices import NoticeJob
from schemas.notice_schema import NOTICE_TYPE_DISPLAY

logger = logging.getLogger(__name__)

# Map notice_type to blueprint JSON file path
NOTICE_BLUEPRINT_MAP = {
    "143_1": "blueprints/notices/notice_143_1_blueprint.json",
    "148": "blueprints/notices/notice_148_blueprint.json",
    "asmt_10": "blueprints/notices/notice_asmt10_blueprint.json",
    "drc_01": "blueprints/notices/notice_drc01_blueprint.json",
    "271_1c": "blueprints/notices/notice_271_1c_blueprint.json",
    "156": "blueprints/notices/notice_156_blueprint.json",
    "traces": "blueprints/notices/notice_traces_blueprint.json",
    "26qb": "blueprints/notices/notice_26qb_blueprint.json",
}

LEGAL_REPLY_PROMPT = """You are an experienced Indian tax practitioner drafting a formal reply to a {notice_type_display} notice.

EXTRACTED DATA FROM NOTICE:
{extracted_json}

SUPPORTING DOCUMENT CONTEXT:
{supporting_context}

Draft a formal legal reply in this format:
1. "To, The Assessing Officer / The Proper Officer" (appropriate for {notice_type})
2. "Subject: Reply to Notice u/s {section} dated [date from extracted data] for AY/Tax Period [period from extracted data]"
3. "Respected Sir/Madam,"
4. Opening paragraph acknowledging receipt
5. Point-by-point response citing supporting evidence
6. Prayer clause requesting relief
7. "Yours faithfully," with placeholder for CA signature

Use formal Indian tax proceeding language. Do NOT fabricate facts. If supporting evidence is insufficient, note that the assessee will furnish the same at the time of hearing."""

# Map notice types to their section references
NOTICE_SECTION_MAP = {
    "143_1": "143(1)",
    "148": "148",
    "asmt_10": "ASMT-10 (Section 61)",
    "drc_01": "73/74",
    "271_1c": "271(1)(c)",
    "156": "156",
    "traces": "200A/201",
    "26qb": "194IA",
}


class NoticeService:
    """Background processing orchestrator for notice reply generation."""

    @staticmethod
    def _is_zero_or_missing(value) -> bool:
        """Check if a value is effectively zero, missing, or placeholder."""
        if value is None:
            return True
        s = str(value).strip().lower()
        # Strip currency symbols and whitespace
        cleaned = s.replace("₹", "").replace("rs", "").replace("rs.", "").replace(",", "").replace(".", "").replace(" ", "").replace("-", "").replace("nil", "0").replace("n/a", "0").replace("not extracted", "0").replace("not available", "0")
        try:
            return float(cleaned) == 0 if cleaned else True
        except ValueError:
            return s in ("", "0", "nil", "n/a", "not extracted", "not available", "none")

    @staticmethod
    def _extract_amount_from_check(value) -> str | None:
        """Try to extract a monetary amount from a check value (string or dict)."""
        import re
        text = ""
        if isinstance(value, dict):
            # Look for keys that suggest an amount
            for k, v in value.items():
                if v and any(word in k.lower() for word in ["amount", "demand", "tax", "total"]):
                    return str(v)
            # Fallback: stringify the whole dict
            text = " ".join(str(v) for v in value.values() if v)
        elif isinstance(value, str):
            text = value
        else:
            return None

        # Find amounts like Rs.20,275 or ₹1,23,450 or 20275
        match = re.search(r'(?:Rs\.?|₹)\s*([\d,]+(?:\.\d+)?)', text)
        if match:
            return f"Rs. {match.group(1)}"
        return None

    @staticmethod
    def _reconcile_summary_with_checks(data: dict, blueprint_dict: dict) -> dict:
        """Cross-reference per-check results into notice_summary when summary has
        zero/missing values but a focused check extracted the actual data.

        Common case: 143(1) intimation where notice_summary.demand_amount = ₹0
        (net payable) but N143_01 correctly extracts the actual demand of Rs.20,275.
        """
        if not data or not isinstance(data, dict):
            return data

        summary = data.get("notice_summary")
        if not summary or not isinstance(summary, dict):
            return data

        # Build a map of check_id → focus from blueprint
        check_focus_map = {}
        if blueprint_dict:
            for check in blueprint_dict.get("checks", []):
                cid = check.get("check_id", "")
                focus = check.get("focus", "").lower()
                check_focus_map[cid] = focus

        # Reconcile demand_amount
        if NoticeService._is_zero_or_missing(summary.get("demand_amount")):
            for check_id, focus in check_focus_map.items():
                if "demand" in focus and "amount" in focus:
                    check_value = data.get(check_id)
                    if check_value:
                        amount = NoticeService._extract_amount_from_check(check_value)
                        if amount and not NoticeService._is_zero_or_missing(amount):
                            logger.info(f"Reconciled demand_amount from {check_id}: {amount}")
                            summary["demand_amount"] = amount
                            break

        # Reconcile response_deadline
        if NoticeService._is_zero_or_missing(summary.get("response_deadline")) or summary.get("response_deadline") in (None, "Not extracted"):
            for check_id, focus in check_focus_map.items():
                if "deadline" in focus or "response" in focus and "date" in focus:
                    check_value = data.get(check_id)
                    if check_value and isinstance(check_value, str) and check_value not in ("null", "None"):
                        summary["response_deadline"] = check_value
                        logger.info(f"Reconciled response_deadline from {check_id}: {check_value}")
                        break

        data["notice_summary"] = summary
        return data

    @staticmethod
    def _flatten_extracted_data(data: dict) -> dict:
        """Flatten nested dicts/lists in extracted_data values into human-readable strings.

        The LLM sometimes returns nested objects for check fields (e.g. N143:02 →
        {"section_reference": "...", "reported_in_itr": "Rs 1,23,450", ...}).
        The frontend expects simple string values, so we convert nested structures
        into "key: value" formatted strings.
        """
        if not data or not isinstance(data, dict):
            return data

        flattened = {}
        for key, value in data.items():
            if key == "notice_summary":
                # Keep notice_summary as-is (frontend handles it separately)
                flattened[key] = value
            elif isinstance(value, dict):
                # Convert dict to "key: value" lines
                parts = []
                for k, v in value.items():
                    if v is not None:
                        parts.append(f"{k.replace('_', ' ').title()}: {v}")
                flattened[key] = "; ".join(parts) if parts else "Not found"
            elif isinstance(value, list):
                # Convert list of dicts or values to readable text
                parts = []
                for item in value:
                    if isinstance(item, dict):
                        sub_parts = [f"{k.replace('_', ' ').title()}: {v}" for k, v in item.items() if v is not None]
                        parts.append("; ".join(sub_parts))
                    else:
                        parts.append(str(item))
                flattened[key] = " | ".join(parts) if parts else "Not found"
            else:
                flattened[key] = value
        return flattened

    @staticmethod
    def _load_notice_blueprint(notice_type: str) -> dict:
        """Load a notice blueprint JSON from disk."""
        bp_path = NOTICE_BLUEPRINT_MAP.get(notice_type)
        if not bp_path:
            raise ValueError(f"No blueprint found for notice type: {notice_type}")

        with open(bp_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _run_extraction(vector_db_path: str, blueprint_dict: dict, notice_filename: str, data_dir: str = None) -> dict:
        """Run synchronous extraction using SecureDocAgent (called via asyncio.to_thread)."""
        from agent import SecureDocAgent

        agent = SecureDocAgent(db_dir=vector_db_path)
        result = agent.extract_notice_fields(
            blueprint_dict,
            metadata_filter={"source": notice_filename},
            data_dir=data_dir,
        )
        # Reconcile summary with per-check results (fixes demand_amount=0 when check has actual value)
        result = NoticeService._reconcile_summary_with_checks(result, blueprint_dict)
        # Flatten nested dicts/lists so frontend gets simple strings
        return NoticeService._flatten_extracted_data(result)

    @staticmethod
    def _run_supporting_query(vector_db_path: str) -> str:
        """Query full vector store for supporting evidence (called via asyncio.to_thread)."""
        from agent import SecureDocAgent

        agent = SecureDocAgent(db_dir=vector_db_path)
        result = agent.query(
            "Summarize all supporting evidence, financial data, and key facts from the uploaded documents.",
            metadata_filter=None,
        )
        return result.get("answer", "No supporting context available.")

    @staticmethod
    def _draft_reply(notice_type: str, extracted_data: dict, supporting_context: str, blueprint_dict: dict = None) -> str:
        """Generate a draft reply using LLM (called via asyncio.to_thread)."""
        from langchain_openai import ChatOpenAI

        notice_type_display = NOTICE_TYPE_DISPLAY.get(notice_type, notice_type)
        section = NOTICE_SECTION_MAP.get(notice_type, notice_type)

        # Build notice details header from extracted notice_summary
        summary = extracted_data.get("notice_summary", {}) if extracted_data else {}
        notice_details = (
            f"NOTICE DETAILS:\n"
            f"- Date: {summary.get('notice_date', 'Not extracted')}\n"
            f"- Section: {summary.get('section_number', section)}\n"
            f"- Assessment Year / Tax Period: {summary.get('assessment_year_or_tax_period', 'Not extracted')}\n"
            f"- Demand Amount: {summary.get('demand_amount', 'Not extracted')}\n"
            f"- Response Deadline: {summary.get('response_deadline', 'Not extracted')}\n"
            f"- Taxpayer: {summary.get('taxpayer_name', 'Not extracted')} ({summary.get('taxpayer_pan_or_gstin', 'Not extracted')})\n"
            f"- Reference Number: {summary.get('notice_reference_number', 'Not extracted')}\n"
        )

        # Build per-check findings section
        check_findings_parts = []
        checks_by_id = {}
        if blueprint_dict:
            for check in blueprint_dict.get("checks", []):
                checks_by_id[check.get("check_id", "")] = check

        for key, value in (extracted_data or {}).items():
            if key == "notice_summary":
                continue
            check_desc = ""
            if key in checks_by_id:
                check_desc = f" ({checks_by_id[key].get('focus', '')})"
            check_findings_parts.append(f"- {key}{check_desc}: {json.dumps(value, default=str)}")

        check_findings = "\n".join(check_findings_parts) if check_findings_parts else "No per-check findings extracted."

        extracted_json = json.dumps(extracted_data, indent=2, default=str)

        prompt_text = LEGAL_REPLY_PROMPT.format(
            notice_type_display=notice_type_display,
            notice_type=notice_type,
            section=section,
            extracted_json=f"{notice_details}\n\nPER-CHECK FINDINGS:\n{check_findings}\n\nFULL EXTRACTED DATA:\n{extracted_json}",
            supporting_context=supporting_context,
        )

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)
        response = llm.invoke(prompt_text)
        return response.content

    @staticmethod
    async def process_notice(notice_job_id: str, vector_db_path: str, data_dir: str = None, thread_id: str = None):
        """Background task: extract data from notice → draft reply.

        Updates NoticeJob status at each stage.
        """
        from api.routes.status import update_audit_status

        logger.info(f"[NOTICE] Background task started for job {notice_job_id}, thread_id={thread_id}")

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(NoticeJob).where(NoticeJob.id == UUID(notice_job_id))
            )
            job = result.scalar_one_or_none()
            if not job:
                logger.error(f"NoticeJob {notice_job_id} not found")
                return

            # Use explicitly passed thread_id (from route), fallback to DB, then job_id
            thread_id = thread_id or job.langgraph_thread_id or str(notice_job_id)

            try:
                # Stage 1: Extracting
                job.status = "extracting"
                await db.commit()
                update_audit_status(thread_id, "extracting", "Extracting key information from notice...", 20)

                blueprint_dict = NoticeService._load_notice_blueprint(job.notice_type)

                extracted = await asyncio.to_thread(
                    NoticeService._run_extraction,
                    vector_db_path,
                    blueprint_dict,
                    job.notice_document_name,
                    data_dir,
                )

                update_audit_status(thread_id, "extracting", "Gathering supporting evidence...", 50)

                # Get supporting context from all docs in the vector store
                supporting_context = await asyncio.to_thread(
                    NoticeService._run_supporting_query,
                    vector_db_path,
                )

                update_audit_status(thread_id, "drafting", "Drafting formal reply...", 70)

                # Stage 2: Draft reply
                draft = await asyncio.to_thread(
                    NoticeService._draft_reply,
                    job.notice_type,
                    extracted,
                    supporting_context,
                    blueprint_dict,
                )

                # Save results
                job.extracted_data = extracted
                job.draft_reply = draft
                job.status = "draft_ready"
                await db.commit()

                update_audit_status(thread_id, "completed", "Draft reply ready for review.", 100)
                logger.info(f"NoticeJob {notice_job_id} draft ready.")

            except Exception as e:
                logger.error(f"NoticeJob {notice_job_id} failed: {e}")
                job.status = "error"
                await db.commit()
                update_audit_status(thread_id, "error", f"Processing failed: {str(e)}", 0)

    @staticmethod
    async def regenerate_notice(notice_job_id: str, new_notice_type: str, vector_db_path: str, data_dir: str = None, thread_id: str = None):
        """Re-generate draft with a different notice type. Reuses existing embeddings."""
        from api.routes.status import update_audit_status

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(NoticeJob).where(NoticeJob.id == UUID(notice_job_id))
            )
            job = result.scalar_one_or_none()
            if not job:
                logger.error(f"NoticeJob {notice_job_id} not found")
                return

            # Use explicitly passed thread_id (from route), fallback to DB, then job_id
            thread_id = thread_id or job.langgraph_thread_id or str(notice_job_id)

            try:
                job.notice_type = new_notice_type
                job.status = "extracting"
                await db.commit()

                update_audit_status(thread_id, "extracting", "Re-extracting with new notice type...", 20)

                blueprint_dict = NoticeService._load_notice_blueprint(new_notice_type)

                extracted = await asyncio.to_thread(
                    NoticeService._run_extraction,
                    vector_db_path,
                    blueprint_dict,
                    job.notice_document_name,
                    data_dir,
                )

                update_audit_status(thread_id, "drafting", "Re-drafting formal reply...", 60)

                supporting_context = await asyncio.to_thread(
                    NoticeService._run_supporting_query,
                    vector_db_path,
                )

                draft = await asyncio.to_thread(
                    NoticeService._draft_reply,
                    new_notice_type,
                    extracted,
                    supporting_context,
                    blueprint_dict,
                )

                job.extracted_data = extracted
                job.draft_reply = draft
                job.status = "draft_ready"
                await db.commit()

                update_audit_status(thread_id, "completed", "New draft ready for review.", 100)

            except Exception as e:
                logger.error(f"NoticeJob {notice_job_id} regenerate failed: {e}")
                job.status = "error"
                await db.commit()
                update_audit_status(thread_id, "error", f"Regeneration failed: {str(e)}", 0)
