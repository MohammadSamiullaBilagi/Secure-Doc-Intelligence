import os
from pathlib import Path
from ingestion import DocumentProcessor

data_dir = r"f:\LLM Engineering\projects\Legal_AI_Expert\user_sessions\f565c3cb-5a01-4fae-b00b-aa82935febb2\data"

print("Initializing DocumentProcessor...")
processor = DocumentProcessor(data_dir=data_dir, db_dir="test_ocr_db")

print("Extracting text...")
docs = processor.extract_text_from_pdfs()

print(f"Extraction returned {len(docs)} pages/documents.")

if docs:
    for i, doc in enumerate(docs):
        print(f"--- Document {i} ---")
        print(f"Metadata: {doc.metadata}")
        print(f"Content preview: {doc.page_content[:200]}...")
else:
    print("No texts extracted.")
