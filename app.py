import os
import shutil
import logging
from pathlib import Path
import gradio as gr
from dotenv import load_dotenv

from ingestion import DocumentProcessor
from agent import SecureDocAgent

# Professional logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

# ==========================================
# Session Management (Multi-User Isolation)
# ==========================================
BASE_SESSIONS_DIR = Path("user_sessions")
BASE_SESSIONS_DIR.mkdir(exist_ok=True)

def get_session_paths(session_hash: str):
    """Creates and returns isolated data and db directories for a specific user session."""
    session_dir = BASE_SESSIONS_DIR / session_hash
    data_dir = session_dir / "data"
    db_dir = session_dir / "vector_db"
    
    data_dir.mkdir(parents=True, exist_ok=True)
    db_dir.mkdir(parents=True, exist_ok=True)
    
    return data_dir, db_dir

def get_available_documents(session_hash: str):
    """Returns a list of PDF filenames currently in the user's specific session directory."""
    if not session_hash:
        return ["All Documents"]
    
    data_dir, _ = get_session_paths(session_hash)
    docs = [f.name for f in data_dir.glob("*.pdf")]
    return ["All Documents"] + docs if docs else ["All Documents"]

# ==========================================
# Core UI Functions
# ==========================================
def process_uploaded_files(files, request: gr.Request):
    """Handles file uploads and isolates them using the user's unique session hash."""
    session_hash = request.session_hash
    data_dir, db_dir = get_session_paths(session_hash)
    
    if not files:
        return gr.update(value="⚠️ No files uploaded."), gr.update()
    
    if not os.getenv("OPENAI_API_KEY"):
        return gr.update(value="❌ Error: OPENAI_API_KEY not found in space secrets."), gr.update()

    status_msg = f"⏳ Processing {len(files)} file(s) for your secure session. Please wait...\n"
    yield gr.update(value=status_msg), gr.update()

    try:
        # 1. Copy uploaded temp files to the USER'S SPECIFIC data directory
        for file in files:
            file_path = Path(file.name)
            destination = data_dir / file_path.name
            shutil.copy(file_path, destination)
            logger.info(f"[Session {session_hash}] Copied {file_path.name}")

        # 2. Run the Ingestion Pipeline pointed strictly at the user's folders
        processor = DocumentProcessor(data_dir=str(data_dir), db_dir=str(db_dir))
        docs = processor.extract_text_from_pdfs()
        
        if not docs:
            yield gr.update(value="❌ Failed to extract text. Files might be corrupted."), gr.update()
            return

        processor.create_vector_store(docs)
        
        # 3. Update the UI Dropdown for this specific user
        new_doc_list = get_available_documents(session_hash)
        status_msg = f"✅ Successfully ingested {len(files)} document(s) into your private database."
        
        yield gr.update(value=status_msg), gr.update(choices=new_doc_list, value="All Documents")

    except Exception as e:
        logger.error(f"[Session {session_hash}] Ingestion error: {e}")
        yield gr.update(value=f"❌ An error occurred: {str(e)}"), gr.update()


def chat_with_agent(message, history, selected_doc, request: gr.Request):
    """Initializes the agent dynamically for the user's specific database and answers."""
    session_hash = request.session_hash
    _, db_dir = get_session_paths(session_hash)

    # Check if this user has a database yet
    if not db_dir.exists() or not any(db_dir.iterdir()):
        return "⚠️ Your private database is empty. Please upload and process documents first."

    if not message.strip():
        return "Please enter a valid question."

    # Set up metadata filter based on dropdown selection
    metadata_filter = None
    if selected_doc and selected_doc != "All Documents":
        metadata_filter = {"source": selected_doc}

    try:
        # Initialize the Agentic Loop pointing strictly to THIS user's database
        agent = SecureDocAgent(db_dir=str(db_dir))
        
        # Query
        result = agent.query(question=message, metadata_filter=metadata_filter)
        
        # Format the response cleanly
        answer = result["answer"]
        citations = result["citations"]
        
        if citations:
            citation_text = "\n\n**Sources:**\n" + "\n".join([f"- `{cite}`" for cite in citations])
            return answer + citation_text
        else:
            return answer

    except Exception as e:
        logger.error(f"[Session {session_hash}] Chat error: {e}")
        return f"❌ An internal error occurred: {str(e)}"

# ==========================================
# Build the Gradio App Layout
# ==========================================
custom_theme = gr.themes.Soft(
    primary_hue="blue",
    secondary_hue="slate",
    font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"]
)

with gr.Blocks(title="Secure Doc-Intelligence") as app:
    gr.Markdown("""
    # ⚖️ Secure Doc-Intelligence Agent
    **Private, Agentic RAG System for Law, Tax, and Compliance.** *Each session is strictly isolated. Your data is wiped when the space restarts.*
    """)
    
    with gr.Row():
        with gr.Column(scale=1, variant="panel"):
            gr.Markdown("### 📂 1. Document Management")
            file_upload = gr.File(label="Upload PDFs", file_types=[".pdf"], file_count="multiple")
            process_btn = gr.Button("⚙️ Process & Ingest Documents", variant="primary")
            status_box = gr.Markdown("Status: *Waiting for files...*")
            
            gr.Markdown("---")
            gr.Markdown("### 🎯 2. Search Settings")
            # Dropdown is initialized empty, populated per-user after upload
            doc_filter = gr.Dropdown(
                label="Strict Document Filter",
                choices=["All Documents"], 
                value="All Documents",
                info="Force the agent to ONLY look at a specific case file."
            )

        with gr.Column(scale=2):
            gr.Markdown("### 💬 Agentic Search")
            chat_interface = gr.ChatInterface(
                fn=chat_with_agent,
                additional_inputs=[doc_filter],
                fill_height=True,
                examples=[
                    ["What are the termination notice requirements?", "All Documents"],
                    ["Are there any specific dates mentioned?", "All Documents"],
                    ["Summarize the key compliance obligations.", "All Documents"]
                ]
            )

    process_btn.click(
        fn=process_uploaded_files,
        inputs=[file_upload],
        outputs=[status_box, doc_filter]
    )

if __name__ == "__main__":
    print("Starting Secure Doc-Intelligence UI with Multi-Tenant Isolation...")
    app.launch(server_name="0.0.0.0", server_port=7860, theme=custom_theme)