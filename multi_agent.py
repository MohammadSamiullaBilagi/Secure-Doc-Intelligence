import logging
import operator
import sqlite3
from typing import TypedDict, Annotated, Dict, List, Any
from pydantic import BaseModel
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_openai import ChatOpenAI

from agent import SecureDocAgent
from schemas.blueprint_schema import Blueprint, AuditResult
from schemas.remediation_schema import RemediationDraft
from services.webhook_service import WebhookService
from utils.exceptions import AgentExecutionError
from config import settings
from pathlib import Path

logger = logging.getLogger(__name__)

class MultiAgentState(TypedDict):
    session_hash: str
    target_contract: str
    blueprint: Blueprint
    extracted_clauses: Dict[str, str] 
    audit_results: Annotated[List[AuditResult], operator.add]
    risk_report: str
    remediation_draft: dict # Stores the serialized RemediationDraft
    status: str

class ComplianceCheckLLMOutput(BaseModel):
    is_compliant: bool
    violation_details: str
    suggested_amendment: str

class RemediationLLMOutput(BaseModel):
    requires_action: bool
    target_recipient_type: str
    email_subject: str
    opening_paragraph: str
    closing_paragraph: str

class ComplianceOrchestrator:
    def __init__(self, db_dir: str):
        self.llm = ChatOpenAI(model="gpt-4o", temperature=0)
        self.doc_agent = SecureDocAgent(db_dir=db_dir)
        self.db_dir = db_dir

    def researcher_node(self, state: MultiAgentState):
        logger.info(f"MULTI-AGENT [Researcher]: Initiating blueprint scan '{state['blueprint'].name}'")
        metadata_filter = {"source": state["target_contract"]} if state["target_contract"] != "All Documents" else None
        
        extracted_clauses = {}
        for check in state["blueprint"].checks:
            try:
                result = self.doc_agent.query(check.focus, metadata_filter=metadata_filter)
                extracted_clauses[check.check_id] = result["answer"]
            except Exception as e:
                logger.error(f"Research failed for check {check.check_id}: {e}")
                extracted_clauses[check.check_id] = f"Extraction System Error: {str(e)}"
                
        return {"extracted_clauses": extracted_clauses, "status": "Research Complete"}

    def auditor_node(self, state: MultiAgentState):
        logger.info("MULTI-AGENT [Auditor]: Evaluating extracted clauses...")
        auditor_llm = self.llm.with_structured_output(ComplianceCheckLLMOutput)
        
        audit_results = []
        for check in state["blueprint"].checks:
            extracted_text = state["extracted_clauses"].get(check.check_id, "No data extracted.")
            prompt = (
                f"You are a strict legal auditor.\n\n"
                f"Extracted Text:\n'{extracted_text}'\n\n"
                f"Mandatory Rule:\n'{check.rule}'\n\n"
                f"Evaluate if the extracted text complies with the rule."
            )
            try:
                llm_response = auditor_llm.invoke(prompt)
                result = AuditResult(
                    check_id=check.check_id, focus=check.focus, rule=check.rule,
                    extracted_clause=extracted_text, is_compliant=llm_response.is_compliant,
                    violation_details=llm_response.violation_details if not llm_response.is_compliant else "None",
                    suggested_amendment=llm_response.suggested_amendment if not llm_response.is_compliant else "None"
                )
                audit_results.append(result)
            except Exception as e:
                logger.error(f"Auditor Node failed on check {check.check_id}: {e}")
                audit_results.append(AuditResult(
                    check_id=check.check_id, focus=check.focus, rule=check.rule,
                    extracted_clause=extracted_text, is_compliant=False,
                    violation_details=f"Auditor system error: {str(e)}", suggested_amendment="Manual review required."
                ))
                
        return {"audit_results": audit_results, "status": "Auditing Complete"}

    def analyst_node(self, state: MultiAgentState):
        logger.info("MULTI-AGENT [Analyst]: Drafting executive report...")
        violations = [res for res in state["audit_results"] if not res.is_compliant]
        
        if not violations:
            final_report = "System Scan Complete. Document is fully compliant. No risks identified."
        else:
            violation_summary = "\n".join([f"- {v.check_id}: {v.violation_details}" for v in violations])
            prompt = (
                f"Based on compliance gaps in '{state['target_contract']}':\n{violation_summary}\n\n"
                f"Write a 3-paragraph executive risk assessment for a Managing Partner. Highlight business risks."
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
                    audit_summary_text += f"- Rule Checked: {v.rule}\n"
                    audit_summary_text += f"  Violation Details: {v.violation_details}\n"
                    audit_summary_text += f"  Suggested Fix: {v.suggested_amendment}\n\n"
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
        violations = [res for res in state["audit_results"] if not res.is_compliant]
        
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

        violation_summary = "\n".join([f"Issue ({v.check_id}): {v.violation_details}\nSuggested Fix: {v.suggested_amendment}" for v in violations])
        
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
                formatted_email += f"{i}. {v.check_id}:\n"
                formatted_email += f"   - Issue: {v.violation_details}\n"
                formatted_email += f"   - Required Action: {v.suggested_amendment}\n\n"
                
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
        """Returns the compiled graph with the SQLite Checkpointer attached."""
        from pathlib import Path
        from langgraph.checkpoint.sqlite import SqliteSaver
        import sqlite3
        from config import settings
        
        db_path = Path(settings.checkpointer_db_path).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        memory = SqliteSaver(conn)
        
        builder = self.build_workflow()
        # CRITICAL: This is what tells the graph to pause BEFORE hitting the dispatch node
        return builder.compile(checkpointer=memory, interrupt_before=["dispatch"])

    def run_blueprint_audit(self, target_contract: str, blueprint: Blueprint, session_hash: str) -> MultiAgentState:
        graph = self.get_compiled_graph()
        
        # FIX 2: Create a totally unique thread ID per document upload to prevent state collisions
        thread_id = f"{session_hash}_{target_contract}"
        
        initial_state = {
            "session_hash": session_hash,
            "target_contract": target_contract,
            "blueprint": blueprint,
            "extracted_clauses": {},
            "audit_results": [],
            "status": "Initializing..."
        }
        
        config = {"configurable": {"thread_id": thread_id}}
        
        try:
            return graph.invoke(initial_state, config=config)
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            raise AgentExecutionError(f"Critical failure in multi-agent workflow: {e}")