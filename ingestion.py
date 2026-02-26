import os
import logging
from pathlib import Path
from typing import List
import fitz  # PyMuPDF
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
        
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=150,
            separators=["\n\n", "\n", ".", " ", ""]
        )
        
        self.data_dir.mkdir(exist_ok=True)
        self.db_dir.mkdir(exist_ok=True)

    def extract_text_from_pdfs(self) -> List[Document]:
        documents = []
        pdf_files = list(self.data_dir.glob("*.pdf"))
        
        if not pdf_files:
            logger.warning(f"No PDF files found in {self.data_dir.absolute()}")
            return documents

        for pdf_path in pdf_files:
            logger.info(f"Processing: {pdf_path.name}")
            try:
                doc = fitz.open(pdf_path)
                num_pages = len(doc) # Fixed logging bug
                
                for page_num in range(num_pages):
                    page = doc.load_page(page_num)
                    text = page.get_text("text").strip()
                    
                    # --- NEW OCR FALLBACK LOGIC ---
                    if not text:
                        logger.info(f"Page {page_num + 1} looks like a scanned image. Running OCR...")
                        try:
                            # Render page to an image (zoom=2 increases DPI for better OCR accuracy)
                            zoom_matrix = fitz.Matrix(2, 2) 
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
                doc.close()
                logger.info(f"Successfully extracted {num_pages} pages from {pdf_path.name}")
                
            except fitz.FileDataError:
                logger.error(f"Corrupted or invalid PDF file: {pdf_path.name}")
            except Exception as e:
                logger.error(f"Failed to process {pdf_path.name}: {str(e)}")
                
        return documents

    def create_vector_store(self, documents: List[Document]):
        if not documents:
            logger.error("No documents to process.")
            return

        logger.info("Chunking documents...")
        chunks = self.text_splitter.split_documents(documents)
        logger.info(f"Created {len(chunks)} total chunks.")

        if not os.getenv("OPENAI_API_KEY"):
            logger.error("OPENAI_API_KEY not found in .env")
            return

        logger.info("Initializing embedding model and ChromaDB...")
        try:
            embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
            
            # Note: If ChromaDB already has data, this appends to it. 
            # If you want a fresh start, delete the vector_db folder first.
            Chroma.from_documents(
                documents=chunks,
                embedding=embeddings,
                persist_directory=str(self.db_dir)
            )
            logger.info(f"Successfully saved {len(chunks)} chunks to {self.db_dir}")
        except Exception as e:
            logger.error(f"Failed to create vector store: {str(e)}")

if __name__ == "__main__":
    processor = DocumentProcessor()
    docs = processor.extract_text_from_pdfs()
    if docs:
        processor.create_vector_store(docs)