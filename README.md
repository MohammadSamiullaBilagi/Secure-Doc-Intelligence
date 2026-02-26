# ⚖️ Secure Doc-Intelligence Agent

An enterprise-grade **Agentic RAG (Retrieval-Augmented Generation)** system built for document-heavy industries such as **Law, Tax, Compliance, and Finance**.

This platform enables secure PDF ingestion (contracts, case files, circulars, audit documents), processes them using advanced OCR + semantic chunking, and provides a high-accuracy chat interface powered by a self-correcting LangGraph agent.

The system guarantees:
- 🔒 Multi-tenant privacy isolation  
- 🧠 Hallucination-resistant answers  
- 📑 Precise page-number citations  
- 🧾 Support for scanned PDFs via OCR  

---

## ✨ Key Features

### 🔐 Multi-Tenant Privacy Isolation
Each user session generates an isolated vector database using secure session hashing.  
Data never crosses between sessions.

### 🤖 Agentic Self-Correction (LangGraph)
A structured evaluation loop validates responses against source documents **before** presenting them to the user.  
If unsupported claims are detected, the agent rewrites the answer automatically.

### 📌 Immaculate Citations
Every response includes:
- Exact document name
- 1-indexed page number
- Clean citation formatting

### 🧾 OCR for Scanned PDFs
If digital text extraction fails, the system automatically falls back to:
- Tesseract OCR
- Page-level image processing
- Cleaned text reconstruction

### 🎯 Strict Metadata Filtering
Users can:
- Query across **All Documents**
- Restrict search to a **specific document only**

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| Orchestration | LangChain + LangGraph |
| LLM | OpenAI `gpt-4o-mini` |
| Embeddings | `text-embedding-3-small` |
| Vector Database | ChromaDB (local persistent storage) |
| PDF Processing | PyMuPDF (`fitz`) |
| OCR | Tesseract (`pytesseract`) |
| Image Handling | Pillow |
| UI | Gradio (Blocks + ChatInterface) |
| Environment | `uv` (fast Python package manager) |

---

## 🏗️ System Architecture Overview
User Upload
↓
PDF Parsing (PyMuPDF)
↓
OCR Fallback (if needed)
↓
Semantic Chunking
↓
OpenAI Embeddings
↓
ChromaDB (Session-Isolated)
↓
LangGraph Agent
↓
Self-Evaluation Loop
↓
Cited Response to User


---

## 🚀 Local Installation

### 1️⃣ Prerequisites

- Python 3.10+
- Tesseract OCR Engine

#### Install Tesseract:

**Windows**
Download from:  
https://github.com/UB-Mannheim/tesseract/wiki  
Make sure the install path matches the configuration in `ingestion.py`.

**Mac**
```bash
brew install tesseract


sudo apt-get install tesseract-ocr

git clone https://github.com/yourusername/secure-doc-agent.git
cd secure-doc-agent

pip install uv

uv venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

uv add langchain \
       langchain-openai \
       langchain-community \
       langgraph \
       chromadb \
       pymupdf \
       pytesseract \
       pillow \
       python-dotenv \
       gradio \
       pydantic

OPENAI_API_KEY="sk-your-api-key-here"

python app.py

http://127.0.0.1:7860