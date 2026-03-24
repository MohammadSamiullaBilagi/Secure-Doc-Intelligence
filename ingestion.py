import os
import json
import hashlib
import logging
from pathlib import Path
from typing import List, Optional
import pymupdf  # PyMuPDF
from dotenv import load_dotenv
from PIL import Image
import pytesseract

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma

# IMPORTANT FOR WINDOWS: Point pytesseract to the installed engine.
# Update this path if you installed Tesseract somewhere else.
if os.name == 'nt':  # Windows
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
else:  # Linux (Hugging Face)
    pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()

class DocumentProcessor:
    def __init__(self, data_dir: str = "data", db_dir: str = "vector_db"):
        self.data_dir = Path(data_dir)
        self.db_dir = Path(db_dir)
        self.hash_cache_file = self.db_dir / "doc_hashes.json"
        self._pending_hash_updates: dict = {}  # Saved only after successful vector store creation

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=150,
            separators=["\n\n", "\n", ".", " ", ""]
        )
        
        self.data_dir.mkdir(exist_ok=True)
        self.db_dir.mkdir(exist_ok=True)

    @staticmethod
    def _compute_file_hash(file_path: Path) -> str:
        """SHA-256 hash of the file to detect duplicates."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _load_hash_cache(self) -> dict:
        """Load cached file hashes."""
        if self.hash_cache_file.exists():
            try:
                return json.loads(self.hash_cache_file.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_hash_cache(self, cache: dict):
        """Save file hashes to cache."""
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.hash_cache_file.write_text(json.dumps(cache))

    def extract_text_from_pdfs(self, only_files: list = None) -> List[Document]:
        documents = []
        pdf_files = list(self.data_dir.glob("*.pdf"))
        
        if not pdf_files:
            logger.warning(f"No PDF files found in {self.data_dir.absolute()}")
            return documents

        # Load hash cache to skip unchanged files
        hash_cache = self._load_hash_cache()
        updated_cache = dict(hash_cache)

        for pdf_path in pdf_files:
            # Filter to specific files if specified
            if only_files and pdf_path.name not in only_files:
                continue
            
            # Check hash — skip if file hasn't changed
            file_hash = self._compute_file_hash(pdf_path)
            if hash_cache.get(pdf_path.name) == file_hash:
                logger.info(f"Skipping {pdf_path.name} — unchanged since last ingestion")
                continue
            
            logger.info(f"Processing: {pdf_path.name}")
            try:
                doc = pymupdf.open(pdf_path)
                num_pages = len(doc) # Fixed logging bug
                try:
                    for page_num in range(num_pages):
                        page = doc.load_page(page_num)
                        text = page.get_text("text").strip()

                        # --- NEW OCR FALLBACK LOGIC ---
                        if not text:
                            logger.info(f"Page {page_num + 1} looks like a scanned image. Running OCR...")
                            try:
                                # Render page to an image (zoom=2 increases DPI for better OCR accuracy)
                                zoom_matrix = pymupdf.Matrix(2, 2)
                                pix = page.get_pixmap(matrix=zoom_matrix)

                                # Convert PyMuPDF pixmap to PIL Image
                                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                                # Extract text using Tesseract
                                text = pytesseract.image_to_string(img).strip()

                                if not text:
                                    logger.warning(f"OCR yielded no text on page {page_num + 1}")
                                    continue
                            except Exception as ocr_error:
                                logger.error(f"OCR failed on page {page_num + 1}: {str(ocr_error)}")
                                continue
                        # ------------------------------

                        documents.append(
                            Document(
                                page_content=text,
                                metadata={
                                    "source": pdf_path.name,
                                    "page": page_num + 1,
                                    "is_scanned": "yes" if not page.get_text("text").strip() else "no" # Tag it for the agent
                                }
                            )
                        )
                finally:
                    doc.close()
                logger.info(f"Successfully extracted {num_pages} pages from {pdf_path.name}")
                
                # --- NEW STEP 1 VALIDATION ---
                total_text_length = sum(len(d.page_content) for d in documents if d.metadata.get("source") == pdf_path.name)
                logger.info(f"VALIDATION (STEP 1): Extracted total {total_text_length} characters from {pdf_path.name}")
                # -----------------------------
                
                updated_cache[pdf_path.name] = file_hash  # Stage: ready to commit after vector store succeeds

            except pymupdf.FileDataError:
                logger.error(f"Corrupted or invalid PDF file: {pdf_path.name}")
            except Exception as e:
                logger.error(f"Failed to process {pdf_path.name}: {str(e)}")

        # Store pending hash updates — committed to disk only after create_vector_store() succeeds
        new_hashes = {k: v for k, v in updated_cache.items() if k not in hash_cache}
        self._pending_hash_updates = new_hashes

        return documents

    def create_vector_store(self, documents: List[Document]):
        if not documents:
            logger.error("No documents to process.")
            return

        logger.info("Chunking documents...")
        chunks = self.text_splitter.split_documents(documents)
        
        # --- NEW STEP 2 METADATA ADDITION ---
        for i, chunk in enumerate(chunks):
            chunk.metadata["chunk_id"] = f"chunk_{i}"
            chunk.metadata["document_id"] = chunk.metadata.get("source", "unknown")
            # Storing the exact text inside metadata might duplicate memory but helps debug retrieval if Chroma cuts it
            chunk.metadata["extracted_text"] = chunk.page_content[:200] + "..." if len(chunk.page_content) > 200 else chunk.page_content
        # ------------------------------------
        
        logger.info(f"VALIDATION (STEP 2): Created {len(chunks)} total chunks with detailed metadata.")

        if not os.getenv("OPENAI_API_KEY"):
            logger.error("OPENAI_API_KEY not found in .env")
            return

        logger.info("Initializing embedding model and ChromaDB...")
        embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

        # Safely clear old vector data using Chroma's API instead of shutil.rmtree
        # This avoids the race condition where background tasks read from a deleted directory
        try:
            existing_store = Chroma(persist_directory=str(self.db_dir), embedding_function=embeddings)
            existing_ids = existing_store._collection.get()["ids"]
            if existing_ids:
                existing_store._collection.delete(ids=existing_ids)
                logger.info(f"Cleared {len(existing_ids)} old vectors from ChromaDB.")
        except Exception:
            pass  # Store doesn't exist yet — will be created below

        Chroma.from_documents(
            documents=chunks,
            embedding=embeddings,
            persist_directory=str(self.db_dir)
        )
        logger.info(f"Successfully saved {len(chunks)} chunks to {self.db_dir}")

        # Commit hash cache only after embeddings succeed — prevents the
        # "hash saved but ChromaDB empty" lock that causes permanent INCONCLUSIVE results
        if self._pending_hash_updates:
            cache = self._load_hash_cache()
            cache.update(self._pending_hash_updates)
            self._save_hash_cache(cache)
            logger.info(f"Hash cache updated for: {list(self._pending_hash_updates.keys())}")
            self._pending_hash_updates = {}

if __name__ == "__main__":
    processor = DocumentProcessor()
    docs = processor.extract_text_from_pdfs()
    if docs:
        processor.create_vector_store(docs)