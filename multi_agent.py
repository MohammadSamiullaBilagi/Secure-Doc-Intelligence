import logging
import operator
import sqlite3
from typing import TypedDict, Annotated, Dict, List, Any
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_openai import ChatOpenAI

from agent import SecureDocAgent
from schemas.blueprint_schema import Blueprint, AuditResult, EnhancedAuditResult
from schemas.remediation_schema import RemediationDraft
from services.webhook_service import WebhookService
from utils.exceptions import AgentExecutionError
from config import settings
from pathlib import Path

logger = logging.getLogger(__name__)

class MultiAgentState(TypedDict):
    session_hash: str
    user_id: str # Explicitly bind the tenant performing the audit
    thread_id: str  # The UUID used for SSE status updates — must match the AuditJob's langgraph_thread_id
    data_dir: str  # Path to the data directory for direct PDF fallback
    target_contract: str
    blueprint: Blueprint
    extracted_fields: Dict[str, Any]
    audit_results: Annotated[List[AuditResult], operator.add]
    risk_report: str
    remediation_draft: dict # Stores the serialized RemediationDraft
    status: str

class ComplianceCheckLLMOutput(BaseModel):
    compliance_status: str = Field(description="Must be 'COMPLIANT', 'PARTIAL', 'NON_COMPLIANT', or 'INCONCLUSIVE'.")
    evidence: str = Field(description="Direct quotes from the document data. Must cite actual field values. Never empty.")
    violation_details: str
    suggested_amendment: str

class RemediationLLMOutput(BaseModel):
    requires_action: bool
    target_recipient_type: str
    email_subject: str
    opening_paragraph: str
    closing_paragraph: str

class ComplianceOrchestrator:
    def __init__(self, db_dir: str, data_dir: str = ""):
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        self.doc_agent = SecureDocAgent(db_dir=db_dir)
        self.db_dir = db_dir
        self.data_dir = data_dir

    def _get_document_text(self, state: MultiAgentState) -> str:
        """Extract raw document text using the existing 3-tier retrieval (ChromaDB → PDF → OCR).

        Refactored from agent.py's extract_structured_fields() Stage 1 logic.
        """
        import pymupdf

        metadata_filter = {"source": state["target_contract"]} if state["target_contract"] != "All Documents" else None
        valid_filter = metadata_filter if metadata_filter else None
        combined_text = ""

        # TIER 1: ChromaDB vector store
        try:
            total_docs = self.doc_agent.local_vectorstore._collection.count()
            k = min(30, total_docs) if total_docs > 0 else 1
            docs = self.doc_agent.local_vectorstore.similarity_search(
                query="document invoice facts terms amounts dates", k=k, filter=valid_filter
            )
            logger.info(f"RESEARCHER [Tier 1 - ChromaDB]: Retrieved {len(docs)} chunks (filter: {valid_filter})")

            if docs:
                docs = [doc for doc in docs if doc.metadata.get("type") != "audit_report"]
                combined_text = "\n\n".join([
                    f"[Page {doc.metadata.get('page', '?')}]: {doc.page_content}"
                    for doc in docs
                ])
        except Exception as e:
            logger.warning(f"RESEARCHER [Tier 1 - ChromaDB]: Vector retrieval failed: {e}")

        # TIER 2: Direct PDF read
        if not combined_text:
            source_filename = valid_filter.get("source") if valid_filter else None
            data_dir = state.get("data_dir", self.data_dir) or self.data_dir
            logger.warning(f"RESEARCHER [Tier 2 - Direct PDF]: ChromaDB returned 0 chunks. Trying '{source_filename}'")

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

                                # Always try pdfplumber for better table extraction
                                try:
                                    import pdfplumber
                                    with pdfplumber.open(pdf_path) as pl_doc:
                                        pl_page = pl_doc.pages[page_num]
                                        if not text:
                                            extracted = pl_page.extract_text()
                                            if extracted:
                                                text = extracted.strip()
                                        tables = pl_page.extract_tables()
                                        if tables:
                                            table_text = "\n".join([
                                                " | ".join([cell if cell else "" for cell in row])
                                                for table in tables for row in table
                                            ])
                                            text += "\n\n[TABLE DATA]:\n" + table_text
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
                        logger.info(f"RESEARCHER [Tier 2 - Direct PDF]: Extracted {len(combined_text)} chars")
                    except Exception as e:
                        logger.error(f"RESEARCHER [Tier 2 - Direct PDF]: Failed: {e}")

            # TIER 2b: Unfiltered ChromaDB (exclude audit_report injections)
            if not combined_text:
                try:
                    docs = self.doc_agent.local_vectorstore.similarity_search(
                        query="document invoice facts terms", k=30, filter=None
                    )
                    if docs:
                        docs = [doc for doc in docs if doc.metadata.get("type") != "audit_report"]
                    if docs:
                        combined_text = "\n\n".join([doc.page_content for doc in docs])
                        logger.info(f"RESEARCHER [Tier 2b - Unfiltered]: Retrieved {len(docs)} chunks")
                except Exception:
                    pass

        return combined_text

    def researcher_node(self, state: MultiAgentState):
        logger.info(f"MULTI-AGENT [Researcher]: Initiating blueprint scan '{state['blueprint'].name}'")

        # Real-time status update for UI
        try:
            from api.routes.status import update_audit_status
            update_audit_status(state['thread_id'], "researching", f"Researcher: Extracting document data for {len(state['blueprint'].checks)} compliance checks...", 40)
        except Exception:
            pass

        # Clean up stale audit_report chunks from previous runs to avoid poisoning extraction
        try:
            collection = self.doc_agent.local_vectorstore._collection
            stale = collection.get(where={"type": "audit_report"}, include=[])
            if stale and stale["ids"]:
                collection.delete(ids=stale["ids"])
                logger.info(f"RESEARCHER: Cleaned up {len(stale['ids'])} stale audit_report chunks from vector store")
        except Exception as e:
            logger.debug(f"RESEARCHER: Audit report cleanup skipped: {e}")

        # Layer 1: Get raw document text via 3-tier retrieval
        combined_text = self._get_document_text(state)

        if not combined_text or len(combined_text.strip()) < 20:
            logger.error("RESEARCHER: No readable text found after all retrieval tiers.")
            return {"extracted_fields": {}, "status": "Research Complete"}

        logger.info(f"RESEARCHER: {len(combined_text)} chars of text available. Running Layer 1 DocumentParser...")

        # Layer 1: Blueprint-agnostic Haiku document parsing
        from services.document_parser import DocumentParser
        parsed_doc = DocumentParser().parse_document(combined_text)

        return {"extracted_fields": parsed_doc, "status": "Research Complete"}

    def auditor_node(self, state: MultiAgentState):
        logger.info("MULTI-AGENT [Auditor]: Evaluating extracted clauses...")

        # Real-time status update for UI
        try:
            from api.routes.status import update_audit_status
            update_audit_status(state['thread_id'], "auditing", f"Auditor: Evaluating {len(state['blueprint'].checks)} compliance rules in parallel...", 60)
        except Exception:
            pass

        audit_results = []
        parsed_doc = state.get("extracted_fields", {})

        # GATE: SYSTEM_ERROR if document is truly unreadable
        if not parsed_doc:
            logger.warning("AUDITOR: No extracted data available. Marking all checks as INCONCLUSIVE.")
            for check in state["blueprint"].checks:
                audit_results.append(AuditResult(
                    check_id=check.check_id,
                    focus=check.focus,
                    rule=check.rule,
                    compliance_status="INCONCLUSIVE",
                    evidence="DOCUMENT EXTRACTION FAILED – Compliance cannot be evaluated.",
                    violation_details="None",
                    suggested_amendment="None"
                ))
            return {"audit_results": audit_results, "status": "Auditing Complete"}

        # Layer 2: Parallel check evaluation with ground truth references
        import asyncio
        from services.check_agent import CheckAgentService

        check_service = CheckAgentService()
        checks = state["blueprint"].checks

        # Run async gather — safe in this thread (called from asyncio.to_thread)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        async def _run_checks():
            results = await check_service.evaluate_all_checks(parsed_doc, checks)
            # Skip verification step — saves 1 LLM call per audit.
            # verify_results() only logs inconsistencies, never re-runs checks.
            return results

        if loop and loop.is_running():
            # We're inside an async context — use nest_asyncio or create a new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, _run_checks())
                check_results = future.result()
        else:
            check_results = asyncio.run(_run_checks())

        # Convert CheckAgentOutput → EnhancedAuditResult for state compatibility
        for cr, check in zip(check_results, checks):
            is_pass = cr.compliance_status in ("COMPLIANT", "INCONCLUSIVE")
            v_det = cr.violation_details if not is_pass else "None"
            s_amend = cr.suggested_amendment if not is_pass else "None"

            fi_dict = None
            if cr.financial_impact:
                fi_dict = cr.financial_impact.model_dump()

            result = EnhancedAuditResult(
                check_id=check.check_id,
                focus=check.focus,
                rule=check.rule,
                compliance_status=cr.compliance_status,
                evidence=cr.evidence,
                violation_details=v_det,
                suggested_amendment=s_amend,
                financial_impact=fi_dict,
                confidence=cr.confidence,
            )
            audit_results.append(result)

        return {"audit_results": audit_results, "status": "Auditing Complete"}

    def analyst_node(self, state: MultiAgentState):
        logger.info("MULTI-AGENT [Analyst]: Drafting executive report...")
        
        # Real-time status update for UI
        try:
            from api.routes.status import update_audit_status
            update_audit_status(state['thread_id'], "analyzing", "Analyst: Generating executive risk assessment...", 80)
        except Exception:
            pass
        
        def _get_status(res):
            if isinstance(res, dict):
                return res.get('compliance_status', res.get('is_compliant', 'NON_COMPLIANT'))
            return getattr(res, 'compliance_status', getattr(res, 'is_compliant', 'NON_COMPLIANT'))
            
        def _get_detail(res):
            if isinstance(res, dict):
                return res.get('violation_details', '')
            return getattr(res, 'violation_details', '')
            
        def _get_id(res):
            if isinstance(res, dict):
                return res.get('check_id', 'Unknown')
            return getattr(res, 'check_id', 'Unknown')
            
        # INCONCLUSIVE = data absent, not a violation. Only NON_COMPLIANT/PARTIAL are real findings.
        violations = [res for res in state["audit_results"] if _get_status(res) in ("NON_COMPLIANT", "PARTIAL")]

        all_inconclusive = state["audit_results"] and all(_get_status(r) == "INCONCLUSIVE" for r in state["audit_results"])

        if all_inconclusive:
            final_report = (
                "EXTRACTION FAILURE: Document text could not be extracted from the vector store. "
                "Please re-upload the document and ensure the API keys are valid, then retry the audit."
            )
        elif not violations:
            final_report = "System Scan Complete. Document is fully compliant. No violations identified."
        else:
            # Build violation summary with financial impact
            violation_lines = []
            total_financial_impact = 0.0
            for v in violations:
                line = f"- {_get_id(v)} [{_get_status(v)}]: {_get_detail(v)}"
                fi = v.get('financial_impact') if isinstance(v, dict) else getattr(v, 'financial_impact', None)
                if fi and isinstance(fi, dict) and fi.get('estimated_amount'):
                    amount = fi['estimated_amount']
                    total_financial_impact += amount
                    line += f" [Financial Impact: Rs. {amount:,.2f} — {fi.get('calculation', '')}]"
                confidence = v.get('confidence', '') if isinstance(v, dict) else getattr(v, 'confidence', '')
                if confidence:
                    line += f" [Confidence: {confidence}]"
                violation_lines.append(line)

            violation_summary = "\n".join(violation_lines)
            financial_note = ""
            if total_financial_impact > 0:
                financial_note = f"\n\nTOTAL ESTIMATED FINANCIAL EXPOSURE: Rs. {total_financial_impact:,.2f}"

            prompt = (
                f"Based on compliance violations found in '{state['target_contract']}':\n{violation_summary}"
                f"{financial_note}\n\n"
                f"Write a CONCISE executive risk summary (MAX 150 words). Format:\n"
                f"1. One-line overall risk verdict with total financial exposure\n"
                f"2. Bullet list of top violations (max 5) — each bullet: section, issue, amount\n"
                f"3. One-line priority recommendation\n\n"
                f"Do NOT write long paragraphs. Use bullet points. Be direct."
            )
            try:
                final_report = self.llm.invoke(prompt).content
            except Exception as e:
                logger.error(f"Analyst Node failed: {e}")
                final_report = "System failed to generate final risk report."

        # ==========================================
        # NEW: MEMORY INJECTION FOR Q&A CHAT
        # ==========================================
        try:
            logger.info("MULTI-AGENT [Analyst]: Injecting findings into Q&A Vector Database...")
            
            # 1. Format a clean, highly searchable summary of the AI's findings
            audit_summary_text = f"--- AI COMPLIANCE AUDIT REPORT FOR {state['target_contract']} ---\n\n"
            audit_summary_text += f"EXECUTIVE RISK ASSESSMENT:\n{final_report}\n\n"
            
            if violations:
                audit_summary_text += "SPECIFIC VIOLATIONS AND GAPS FOUND:\n"
                for v in violations:
                    rule = v.get('rule', '') if isinstance(v, dict) else getattr(v, 'rule', '')
                    evidence = v.get('evidence', '') if isinstance(v, dict) else getattr(v, 'evidence', '')
                    s_amend = v.get('suggested_amendment', '') if isinstance(v, dict) else getattr(v, 'suggested_amendment', '')
                    
                    audit_summary_text += f"- Rule Checked: {rule}\n"
                    audit_summary_text += f"  Status: {_get_status(v)}\n"
                    audit_summary_text += f"  Evidence: {evidence}\n"
                    audit_summary_text += f"  Violation Details: {_get_detail(v)}\n"
                    audit_summary_text += f"  Suggested Fix: {s_amend}\n\n"
            else:
                audit_summary_text += "No violations found during the compliance scan.\n"

            # 2. Create a LangChain Document
            from langchain_core.documents import Document
            audit_doc = Document(
                page_content=audit_summary_text,
                metadata={
                    "source": state["target_contract"], # Tagged with the same PDF filename!
                    "page": "AI Audit Summary",         # So the user sees where it came from in citations
                    "type": "audit_report"
                }
            )

            # 3. Inject it into the local ChromaDB for this specific session
            self.doc_agent.local_vectorstore.add_documents([audit_doc])
            logger.info("Successfully injected Audit Report into Q&A memory.")
            
        except Exception as e:
            logger.error(f"Failed to inject audit memory into Vector DB: {e}")
        # ==========================================

        return {"risk_report": final_report, "status": "Risk Assessment Complete"}

    def remediation_node(self, state: MultiAgentState):
        logger.info("MULTI-AGENT [Remediation]: Assessing needed actions...")
        
        # Real-time status update for UI
        try:
            from api.routes.status import update_audit_status
            update_audit_status(state['thread_id'], "remediating", "Remediation: Drafting corrective actions...", 90)
        except Exception:
            pass
        
        def _get_status(res):
            if isinstance(res, dict):
                return res.get('compliance_status', res.get('is_compliant', 'NON_COMPLIANT'))
            return getattr(res, 'compliance_status', getattr(res, 'is_compliant', 'NON_COMPLIANT'))
            
        def _get_detail(res):
            if isinstance(res, dict):
                return res.get('violation_details', '')
            return getattr(res, 'violation_details', '')
            
        def _get_id(res):
            if isinstance(res, dict):
                return res.get('check_id', 'Unknown')
            return getattr(res, 'check_id', 'Unknown')
            
        def _get_amend(res):
            if isinstance(res, dict):
                return res.get('suggested_amendment', '')
            return getattr(res, 'suggested_amendment', '')

        # INCONCLUSIVE = data absent, not a violation. Only NON_COMPLIANT/PARTIAL require remediation.
        violations = [res for res in state["audit_results"] if _get_status(res) in ("NON_COMPLIANT", "PARTIAL")]

        # We use our new schema here!
        remediation_llm = self.llm.with_structured_output(RemediationLLMOutput)

        if not violations:
            logger.info("No violations found. Skipping remediation drafting.")
            draft = {
                "requires_action": False,
                "target_recipient_type": "None",
                "email_subject": "Compliance Scan Successful",
                "email_body": "The document passed all compliance checks. No further action is required."
            }
            return {"remediation_draft": draft, "status": "Finished"}

        violation_summary = "\n".join([f"Issue ({_get_id(v)}): {_get_detail(v)}\nSuggested Fix: {_get_amend(v)}" for v in violations])
        
        prompt = (
            f"You are a professional legal compliance officer.\n"
            f"Review the following contract violations found in '{state['target_contract']}':\n\n"
            f"{violation_summary}\n\n"
            f"Write a formal 'Correction Request' email to the external vendor or internal team. "
            f"ONLY provide the opening paragraph and the closing paragraph. "
            f"Do NOT write the bullet points of the violations. The system will inject them automatically."
        )

        try:
            llm_result = remediation_llm.invoke(prompt)
            
            # ==========================================
            # THE FIX: PYTHON-DRIVEN FORMATTING
            # ==========================================
            # Python guarantees absolute control over line breaks and bullet points
            formatted_email = f"{llm_result.opening_paragraph}\n\n"
            formatted_email += "Identified Issues and Required Corrections:\n\n"
            
            for i, v in enumerate(violations, 1):
                formatted_email += f"{i}. {_get_id(v)}:\n"
                formatted_email += f"   - Issue: {_get_detail(v)}\n"
                formatted_email += f"   - Required Action: {_get_amend(v)}\n"
                fi = v.get('financial_impact') if isinstance(v, dict) else getattr(v, 'financial_impact', None)
                if fi and isinstance(fi, dict) and fi.get('estimated_amount'):
                    formatted_email += f"   - Estimated Financial Impact: Rs. {fi['estimated_amount']:,.2f}\n"
                formatted_email += "\n"
                
            formatted_email += f"{llm_result.closing_paragraph}"
            # ==========================================
            
            draft = {
                "requires_action": llm_result.requires_action,
                "target_recipient_type": llm_result.target_recipient_type,
                "email_subject": llm_result.email_subject,
                "email_body": formatted_email
            }
            
        except Exception as e:
            logger.error(f"Remediation Node failed: {e}")
            draft = {
                "requires_action": True, 
                "target_recipient_type": "Unknown",
                "email_subject": "URGENT: Contract Compliance Review Required",
                "email_body": "An automated system error prevented email drafting. Please review the attached risk report manually."
            }

        return {"remediation_draft": draft, "status": "Finished"}
    def dispatch_node(self, state: MultiAgentState):
        """NEW: The Execution Layer. This node is strictly guarded by HITL."""
        logger.info(f"MULTI-AGENT [Dispatch]: Firing webhook for {state['target_contract']}")
        
        # Only dispatch if action is actually required
        draft = state.get("remediation_draft", {})
        if draft.get("requires_action", False):
            # Make sure WebhookService is imported at the top of your file!
            from services.webhook_service import WebhookService 
            
            WebhookService.dispatch_audit_results(
                session_hash=state["session_hash"],
                filename=state["target_contract"],
                final_state=state
            )
            return {"status": "Dispatched"}
        
        return {"status": "Completed without dispatch"}

    def build_workflow(self) -> StateGraph:
        builder = StateGraph(MultiAgentState)
        
        # 1. Register ALL nodes
        builder.add_node("researcher", self.researcher_node)
        builder.add_node("auditor", self.auditor_node)
        builder.add_node("analyst", self.analyst_node)
        builder.add_node("remediation", self.remediation_node)
        builder.add_node("dispatch", self.dispatch_node) # <-- CRITICAL: Must be added
        
        # 2. Wire the edges in order
        builder.set_entry_point("researcher")
        builder.add_edge("researcher", "auditor")
        builder.add_edge("auditor", "analyst")
        builder.add_edge("analyst", "remediation")
        
        # CRITICAL FIX: Remediation must go to dispatch, NOT to END
        builder.add_edge("remediation", "dispatch") 
        builder.add_edge("dispatch", END) 
        
        return builder
    
    def get_compiled_graph(self):
        """Returns the compiled graph with a checkpointer (SQLite for dev, PostgreSQL for prod)."""
        from config import settings

        if settings.is_sqlite:
            from pathlib import Path
            from langgraph.checkpoint.sqlite import SqliteSaver
            import sqlite3

            db_path = Path(settings.checkpointer_db_path).resolve()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            memory = SqliteSaver(conn)
        else:
            from langgraph.checkpoint.postgres import PostgresSaver
            import psycopg

            db_url = settings.sync_database_url
            # Setup requires autocommit=True because some migrations use
            # CREATE INDEX CONCURRENTLY which cannot run in a transaction.
            try:
                setup_conn = psycopg.connect(db_url, autocommit=True)
                try:
                    PostgresSaver(setup_conn).setup()
                finally:
                    setup_conn.close()
            except Exception as e:
                logger.warning(f"Checkpointer setup (may already exist): {e}")

            # Normal connection for checkpoint reads/writes
            conn = psycopg.connect(db_url)
            memory = PostgresSaver(conn)

        builder = self.build_workflow()
        # CRITICAL: This is what tells the graph to pause BEFORE hitting the dispatch node
        return builder.compile(checkpointer=memory, interrupt_before=["dispatch"])

    def run_blueprint_audit(self, target_contract: str, blueprint: Blueprint, session_hash: str, user_id: str, thread_id: str = None) -> MultiAgentState:
        graph = self.get_compiled_graph()

        # Use the caller-provided thread_id (UUID-based) to ensure each audit run is isolated.
        # Falling back to the old deterministic format only if no thread_id is passed (e.g. tests).
        if not thread_id:
            import uuid
            thread_id = str(uuid.uuid4())
            logger.warning(f"No thread_id provided to run_blueprint_audit — generated fallback: {thread_id}")

        initial_state = {
            "session_hash": session_hash,
            "user_id": user_id,
            "thread_id": thread_id,
            "data_dir": self.data_dir,
            "target_contract": target_contract,
            "blueprint": blueprint,
            "extracted_fields": {},
            "audit_results": [],
            "status": "Initializing..."
        }
        
        config = {"configurable": {"thread_id": thread_id}}
        
        try:
            return graph.invoke(initial_state, config=config)
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            raise AgentExecutionError(f"Critical failure in multi-agent workflow: {e}")