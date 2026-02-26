import os
import shutil
import logging
from pathlib import Path
import gradio as gr
from dotenv import load_dotenv

from ingestion import DocumentProcessor
from agent import SecureDocAgent
from multi_agent import ComplianceOrchestrator # Import the new Multi-Agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

BASE_SESSIONS_DIR = Path("user_sessions")
BASE_SESSIONS_DIR.mkdir(exist_ok=True)

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
def process_uploaded_files(files, request: gr.Request):
    if request is None:
        yield gr.update(value="⚠️ System initializing..."), gr.update(), gr.update()
        return
        
    session_hash = request.session_hash
    data_dir, db_dir = get_session_paths(session_hash)
    
    if not files:
        yield gr.update(value="⚠️ No files uploaded."), gr.update(), gr.update()
        return

    status_msg = f"⏳ Processing {len(files)} file(s). Please wait...\n"
    yield gr.update(value=status_msg), gr.update(), gr.update()

    try:
        for file in files:
            file_path = Path(file.name)
            destination = data_dir / file_path.name
            shutil.copy(file_path, destination)

        processor = DocumentProcessor(data_dir=str(data_dir), db_dir=str(db_dir))
        docs = processor.extract_text_from_pdfs()
        
        if docs:
            processor.create_vector_store(docs)
            new_doc_list = get_available_documents(session_hash)
            status_msg = f"✅ Successfully ingested {len(files)} document(s)."
            # Update BOTH dropdowns (Chat tab and Audit tab)
            yield gr.update(value=status_msg), gr.update(choices=new_doc_list, value="All Documents"), gr.update(choices=new_doc_list, value="All Documents")
        else:
            yield gr.update(value="❌ Failed to extract text."), gr.update(), gr.update()
            
    except Exception as e:
        logger.error(f"[Session {session_hash}] Ingestion error: {e}")
        yield gr.update(value=f"❌ Error: {str(e)}"), gr.update(), gr.update()

# --- TAB 2: Standard Chat ---
def chat_with_agent(message, history, selected_doc, request: gr.Request):
    if request is None:
        return "System is initializing. Please try again."
        
    session_hash = request.session_hash
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

# --- TAB 3: Multi-Agent Audit ---
def run_compliance_audit(selected_doc, research_query, audit_framework, request: gr.Request):
    if request is None:
        return "System is initializing...", None
        
    session_hash = request.session_hash
    _, db_dir = get_session_paths(session_hash)

    if not db_dir.exists() or not any(db_dir.iterdir()):
        return "⚠️ Database is empty. Please upload documents first.", None
        
    if not research_query or not audit_framework:
        return "⚠️ Please provide both the clauses to extract and the compliance framework.", None

    try:
        orchestrator = ComplianceOrchestrator(db_dir=str(db_dir))
        
        # Notice we pass session_hash now, and it returns two items!
        result_state, pdf_path = orchestrator.run_audit(
            target_contract=selected_doc,
            research_query=research_query,
            audit_framework=audit_framework,
            session_hash=session_hash
        )
        
        # Format the output beautifully for the UI
        markdown_report = f"""
## 📄 Audit Target: {selected_doc}

### 🔍 1. Researcher Agent Found:
> {result_state['extracted_clauses'][0]}

---

### ⚖️ 2. Auditor Agent Review:
{result_state['compliance_gaps'][0]}

---

### 📊 3. Final Risk Assessment (Managing Partner Brief):
{result_state['risk_report']}
        """
        # Return the markdown for the screen, and the file path for the download component
        return markdown_report, gr.update(value=pdf_path, visible=True)

    except Exception as e:
        logger.error(f"Audit failure: {e}")
        return f"❌ Workflow failed: {str(e)}"

# ==========================================
# Build the Gradio App Layout
# ==========================================
custom_theme = gr.themes.Soft(primary_hue="blue", secondary_hue="slate")

with gr.Blocks(title="Secure Doc-Intelligence", theme=custom_theme) as app:
    gr.Markdown("# ⚖️ AI Legal Operating System\n*Agentic RAG & Multi-Agent Compliance Automation.*")
    
    with gr.Row():
        # LEFT PANEL: Global Controls
        with gr.Column(scale=1, variant="panel"):
            gr.Markdown("### 📂 1. Document Management")
            file_upload = gr.File(label="Upload PDFs", file_types=[".pdf"], file_count="multiple")
            process_btn = gr.Button("⚙️ Process Documents", variant="primary")
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
                with gr.Tab("🔎 Deep Compliance Audit"):
                    gr.Markdown("Trigger a 3-Agent workflow (Researcher -> Auditor -> Analyst) to evaluate a contract against specific regulations.")
                    
                    audit_filter = gr.Dropdown(label="Target Contract to Audit", choices=["All Documents"], value="All Documents")
                    
                    query_input = gr.Textbox(
                        label="Step 1: What should the Researcher Agent extract?",
                        placeholder="e.g., Extract all clauses related to Default Loss Guarantee, liability, and data privacy."
                    )
                    
                    framework_input = gr.Textbox(
                        label="Step 2: What rules should the Auditor Agent enforce?",
                        placeholder="e.g., The contract must state that liability is capped at 10% and data cannot be shared with third-party vendors.",
                        lines=3
                    )
                    
                    audit_btn = gr.Button("🚀 Run Multi-Agent Audit", variant="stop")
                    audit_output = gr.Markdown(label="Final Report", value="*The generated risk report will appear here...*")
                    # NEW: The invisible file download component that appears when the PDF is ready
                    pdf_download = gr.File(label="📥 Download Executive Report", visible=False)


    # Wire up the UI events
    process_btn.click(
        fn=process_uploaded_files,
        inputs=[file_upload],
        outputs=[status_box, chat_filter, audit_filter] # Updates both dropdowns!
    )
    
    audit_btn.click(
        fn=run_compliance_audit,
        inputs=[audit_filter, query_input, framework_input],
        outputs=[audit_output,pdf_download]
    )

if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7860)