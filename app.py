import os
import shutil
import logging
from pathlib import Path
import gradio as gr
from dotenv import load_dotenv
import requests
import asyncio
from Database.database import init_db, SessionLocal
from repositories.session_repository import SessionRepository
from services.scheduler import start_background_tasks
from config import settings
from ingestion import DocumentProcessor
from agent import SecureDocAgent
from multi_agent import ComplianceOrchestrator # Import the new Multi-Agent
from services.approval_service import ApprovalService
from services.watcher_service import WatcherService
from services.blueprint_service import BlueprintService
from services.watcher_service import WatcherService

init_db()
start_background_tasks()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

BASE_SESSIONS_DIR = Path("user_sessions")
BASE_SESSIONS_DIR.mkdir(exist_ok=True)

AUDIT_TEMPLATES = {
    "Custom (Type your own)": {
        "query": "Extract all clauses related to...",
        "framework": "The contract must comply with..."
    },
    "RBI Digital Lending (2025-26)": {
        "query": "Extract clauses related to Default Loss Guarantee (DLG), Cooling-off periods, APR disclosure, and Data Privacy/Third-party sharing.",
        "framework": "1. DLG must not exceed 5%. 2. Cooling-off period must be min 3 days for loans > 7 days. 3. APR must be disclosed in the KFS. 4. Data cannot be shared without explicit, revocable consent."
    },
    "GST Input Tax Credit (Section 16/17)": {
        "query": "Extract the vendor GSTIN, invoice date, and the nature of goods/services provided.",
        "framework": "1. Verify if the item falls under Blocked Credits (Section 17(5)) like motor vehicles or food. 2. Ensure the invoice is not older than the filing deadline. 3. Flag any missing state-specific tax splits (CGST/SGST/IGST)."
    },
    "Corporate Lease Risk Scan": {
        "query": "Extract the Force Majeure clause, the Termination notice period, and the Sub-letting permissions.",
        "framework": "1. Force Majeure must explicitly include 'Pandemics' or 'Epidemics'. 2. Termination notice for the Lessee must not exceed 60 days. 3. Sub-letting must be prohibited without prior written consent."
    }
}

def trigger_heartbeat(session_hash: str):
    """Utility to ping the DB on user interaction."""
    if not session_hash: return
    db = SessionLocal()
    try:
        repo = SessionRepository(db)
        repo.heartbeat(session_hash)
    except Exception as e:
        logger.error(f"Heartbeat failed for {session_hash}: {e}")
    finally:
        db.close()

def get_session_paths(session_hash: str):
    session_dir = BASE_SESSIONS_DIR / session_hash
    data_dir = session_dir / "data"
    db_dir = session_dir / "vector_db"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_dir.mkdir(parents=True, exist_ok=True)
    return data_dir, db_dir

def get_available_documents(session_hash: str):
    if not session_hash:
        return ["All Documents"]
    data_dir, _ = get_session_paths(session_hash)
    docs = [f.name for f in data_dir.glob("*.pdf")]
    return ["All Documents"] + docs if docs else ["All Documents"]

# --- TAB 1: Ingestion ---
async def process_uploaded_files(files, selected_blueprint_file, request: gr.Request):
    if request is None:
        yield gr.update(value="⚠️ System initializing..."), gr.update()
        return
        
    session_hash = request.session_hash
    trigger_heartbeat(session_hash)
    data_dir, db_dir = get_session_paths(session_hash)
    
    if not files:
        yield gr.update(value="⚠️ No files uploaded."), gr.update()
        return

    status_msg = f"⏳ Processing {len(files)} file(s). Please wait...\n"
    yield gr.update(value=status_msg), gr.update()

    try:
        # 1. Copy uploaded files to the isolated session directory
        for file in files:
            file_path = Path(file.name)
            destination = data_dir / file_path.name
            shutil.copy(file_path, destination)

        # 2. Extract and embed the text
        processor = DocumentProcessor(data_dir=str(data_dir), db_dir=str(db_dir))
        docs = processor.extract_text_from_pdfs()
        
        if docs:
            processor.create_vector_store(docs)
            new_doc_list = get_available_documents(session_hash)
            status_msg = f"✅ Successfully ingested {len(files)} document(s)."
            
            # Update the UI
            yield gr.update(value=status_msg), gr.update(choices=new_doc_list, value="All Documents")
            
            # 3. --- The Push Trigger ---
            # This MUST happen after processor.create_vector_store(docs) completes!
            for file in files:
                filename = Path(file.name).name
                logger.info(f"Triggering Watcher for {filename} using blueprint: {selected_blueprint_file}")
                
                # Spawn the background audit task with the user's chosen blueprint
                asyncio.create_task(WatcherService.run_background_audit(
                    session_hash=session_hash, 
                    filename=filename, 
                    selected_blueprint_file=selected_blueprint_file
                ))
                
        else:
            yield gr.update(value="❌ Failed to extract text."), gr.update()
            
    except Exception as e:
        logger.error(f"Ingestion error: {e}")
        yield gr.update(value=f"❌ Error: {str(e)}"), gr.update()

# --- TAB 2: Standard Chat ---
def chat_with_agent(message, history, selected_doc, request: gr.Request):
    if request is None:
        return "System is initializing. Please try again."
        
    session_hash = request.session_hash
    trigger_heartbeat(session_hash)
    _, db_dir = get_session_paths(session_hash)

    if not db_dir.exists() or not any(db_dir.iterdir()):
        return "⚠️ Database is empty. Please upload documents first."

    metadata_filter = {"source": selected_doc} if selected_doc and selected_doc != "All Documents" else None

    try:
        agent = SecureDocAgent(db_dir=str(db_dir))
        result = agent.query(question=message, metadata_filter=metadata_filter)
        
        answer = result["answer"]
        citations = "\n\n**Sources:**\n" + "\n".join([f"- `{c}`" for c in result["citations"]]) if result["citations"] else ""
        return answer + citations
    except Exception as e:
        return f"❌ Error: {str(e)}"

def fetch_pending_task(request: gr.Request):
    logger.info("--- FETCH PENDING TASK INITIATED BY UI ---")
    if not request: 
        return gr.update(visible=False), "", "", "No session active.", ""
    
    session_hash = request.session_hash
    data_dir, db_dir = get_session_paths(session_hash)
    
    if not db_dir.exists() or not any(db_dir.iterdir()):
        return gr.update(visible=False), "", "", "Database not ready. Please process documents first.", ""

    try:
        orchestrator = ComplianceOrchestrator(db_dir=str(db_dir))
        approval_svc = ApprovalService(orchestrator)
        
        # Safely find all PDFs we've ingested in this session
        if data_dir.exists():
            pdf_files = list(data_dir.glob("*.pdf"))
            logger.info(f"UI found {len(pdf_files)} uploaded PDF(s) to check.")
            
            for pdf_file in pdf_files:
                filename = pdf_file.name
                
                # This MUST exactly match the thread_id format used in multi_agent.py
                thread_id = f"{session_hash}_{filename}" 
                logger.info(f"Querying checkpointer for thread: {thread_id}")
                
                pending_state = approval_svc.get_pending_approval(thread_id)
                
                if pending_state:
                    remediation = pending_state.get("remediation_draft", {})
                    
                    if remediation.get("requires_action"):
                        risk_report = pending_state.get("risk_report", "")
                        email_draft = remediation.get("email_body", "")
                        status = f"⚠️ Action Required for: {filename}"
                        
                        logger.info(f"Pushing drafted email for {filename} to Gradio UI!")
                        # Push the data to the Gradio components
                        return gr.update(visible=True), risk_report, email_draft, status, thread_id
                    else:
                        logger.info(f"Task for {filename} requires no action. Skipping.")
                        
    except Exception as e:
        logger.error(f"Error fetching tasks: {e}", exc_info=True)
        return gr.update(visible=False), "", "", f"❌ System Error: {e}", ""
        
    logger.info("No matching paused tasks found in checkpointer.")
    return gr.update(visible=False), "", "", "✅ No pending actions.", ""
def approve_task(edited_draft, active_thread_id, request: gr.Request):
    if not request or not active_thread_id: return "Error: No active task to approve."
    session_hash = request.session_hash
    _, db_dir = get_session_paths(session_hash)
    
    try:
        orchestrator = ComplianceOrchestrator(db_dir=str(db_dir))
        approval_svc = ApprovalService(orchestrator)
        approval_svc.approve_and_resume(active_thread_id, edited_draft) # Passes the unique thread
        return "✅ Approved and Dispatched to Automations!"
    except Exception as e:
        return f"❌ Error: {str(e)}"

def reject_task(active_thread_id, request: gr.Request):
    if not request or not active_thread_id: return "Error: No active task to reject."
    session_hash = request.session_hash
    _, db_dir = get_session_paths(session_hash)
    
    try:
        orchestrator = ComplianceOrchestrator(db_dir=str(db_dir))
        approval_svc = ApprovalService(orchestrator)
        approval_svc.reject_and_cancel(active_thread_id)
        return "🚫 Rejected. Action Canceled."
    except Exception as e:
        return f"❌ Error: {str(e)}"



# --- TAB 3: Multi-Agent Audit ---

        
 

# ==========================================
# Build the Gradio App Layout
# ==========================================
custom_theme = gr.themes.Soft(primary_hue="blue", secondary_hue="slate")

with gr.Blocks(title="Secure Doc-Intelligence", theme=custom_theme) as app:
    gr.Markdown("# ⚖️ AI Legal Operating System\n*Agentic RAG & Multi-Agent Compliance Automation.*")
    
    with gr.Row():
        # LEFT PANEL: Global Controls
        with gr.Column(scale=1, variant="panel"):
            gr.Markdown("### 📂 1. Document & Audit Setup")
            
            # NEW: The Blueprint Selector Dropdown
            available_blueprints = BlueprintService.get_available_blueprints()
            default_bp = available_blueprints[0] if available_blueprints else None
            
            blueprint_dropdown = gr.Dropdown(
                label="Select Compliance Framework",
                choices=available_blueprints,
                value=default_bp,
                info="The Watcher Agent will automatically audit against this rule set."
            )
            
            file_upload = gr.File(label="Upload PDFs", file_types=[".pdf"], file_count="multiple")
            process_btn = gr.Button("⚙️ Process & Run Audit", variant="primary")
            status_box = gr.Markdown("Status: *Waiting for files...*")
            
        # RIGHT PANEL: The App Tabs
        with gr.Column(scale=2):
            with gr.Tabs():
                
                # --- TAB 1: Basic RAG Chat ---
                with gr.Tab("💬 Q&A Chat"):
                    chat_filter = gr.Dropdown(label="Document Filter", choices=["All Documents"], value="All Documents")
                    chat_interface = gr.ChatInterface(
                        fn=chat_with_agent,
                        additional_inputs=[chat_filter],
                        cache_examples=False,
                        fill_height=True
                    )
                
                # --- TAB 2: Multi-Agent Auditor ---
                
                
                with gr.Tab("🚦 Pending Approvals"):
                    gr.Markdown("Review automated actions generated by the system before they are dispatched.")
                    
                    active_thread = gr.State(value="")

                    refresh_btn = gr.Button("🔄 Refresh Tasks")
                    status_banner = gr.Markdown("✅ No pending actions.")
                    
                    # The Action Panel (Hidden by default until a task is found)
                    with gr.Group(visible=False) as action_panel:
                        gr.Markdown("### 📊 AI Risk Assessment")
                        risk_review = gr.Markdown(value="*Loading...*")
                        
                        gr.Markdown("### ✉️ Drafted Remediation (Editable)")
                        draft_editor = gr.Textbox(lines=10, label="Edit the AI's email draft before sending")
                        
                        with gr.Row():
                            approve_btn = gr.Button("✅ Approve & Send Workflow", variant="primary")
                            reject_btn = gr.Button("❌ Reject & Cancel", variant="stop")

                    refresh_btn.click(
                        fn=fetch_pending_task,
                        inputs=[],
                        outputs=[action_panel, risk_review, draft_editor, status_banner, active_thread]
                    )
                    
                    approve_btn.click(
                        fn=approve_task,
                        inputs=[draft_editor, active_thread],
                        outputs=[status_banner]
                    ).then(
                        fn=fetch_pending_task, inputs=[], outputs=[action_panel, risk_review, draft_editor, status_banner, active_thread]
                    )
                    
                    reject_btn.click(
                        fn=reject_task,
                        inputs=[active_thread],
                        outputs=[status_banner]
                    ).then(
                        fn=fetch_pending_task, inputs=[], outputs=[action_panel, risk_review, draft_editor, status_banner, active_thread]
                    )
    
    process_btn.click(
    fn=process_uploaded_files,
    # Pass the files AND the value of the blueprint dropdown into the function
    inputs=[file_upload, blueprint_dropdown], 
    # Update only the status box and the chat dropdown
    outputs=[status_box, chat_filter] 
)
    

if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7860)