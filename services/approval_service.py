import logging
from typing import Dict, Any, Optional
from multi_agent import ComplianceOrchestrator
from utils.exceptions import ApprovalStateError

logger = logging.getLogger(__name__)

class ApprovalService:
    def __init__(self, orchestrator: ComplianceOrchestrator):
        self.graph = orchestrator.get_compiled_graph()

    def get_pending_approval(self, thread_id: str) -> Optional[Dict[str, Any]]:
        """Checks if a specific thread is paused at the dispatch node."""
        config = {"configurable": {"thread_id": thread_id}}
        state_snapshot = self.graph.get_state(config)
        
        # 1. If the checkpointer has never heard of this thread
        if not state_snapshot or not hasattr(state_snapshot, 'next'):
            logger.info(f"Checkpointer has no record of thread: {thread_id}")
            return None
            
        # 2. Log exactly what LangGraph is currently paused on
        logger.info(f"Thread {thread_id} is currently paused on next node(s): {state_snapshot.next}")
        
        # 3. Check if 'dispatch' is anywhere in the queued next actions
        if state_snapshot.next and 'dispatch' in state_snapshot.next:
            logger.info(f"✅ Found paused dispatch state for {thread_id}!")
            return state_snapshot.values
            
        return None
    def approve_and_resume(self, thread_id: str, edited_email_body: str) -> Dict[str, Any]:
        logger.info(f"Human Approval Received. Resuming dispatch.")
        config = {"configurable": {"thread_id": thread_id}}
        
        current_state = self.graph.get_state(config)
        if not current_state or 'dispatch' not in current_state.next:
            raise ApprovalStateError("Cannot approve. Graph is not in a pending dispatch state.")

        current_draft = current_state.values.get("remediation_draft", {})
        current_draft["email_body"] = edited_email_body
        
        self.graph.update_state(config, {"remediation_draft": current_draft})
        return self.graph.invoke(None, config=config)

    def reject_and_cancel(self, thread_id: str):
        logger.info(f"Human Rejection Received. Canceling dispatch.")
        config = {"configurable": {"thread_id": thread_id}}
        
        current_state = self.graph.get_state(config)
        if not current_state or 'dispatch' not in current_state.next:
            raise ApprovalStateError("Cannot reject. Graph is not in a pending dispatch state.")

        current_draft = current_state.values.get("remediation_draft", {})
        current_draft["requires_action"] = False 
        current_draft["email_body"] = "[CANCELED BY HUMAN]"
        
        self.graph.update_state(config, {"remediation_draft": current_draft})
        self.graph.invoke(None, config=config)