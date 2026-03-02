import logging
from typing import List
from tenacity import retry, stop_after_attempt, wait_exponential
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from config import settings
from utils.exceptions import ScrapingError

logger = logging.getLogger(__name__)

class KnowledgeFreshnessService:
    def __init__(self):
        self.search_tool = TavilySearchResults(max_results=5, api_key=settings.tavily_api_key)
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        self.text_splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=200)
        self.global_db_dir = settings.global_db_dir

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _fetch_regulatory_updates(self, query: str) -> List[dict]:
        """Fetches updates with exponential backoff for network resilience."""
        logger.info(f"Scraping global updates for: {query}")
        return self.search_tool.invoke({"query": query})

    def run_weekly_update(self):
        """Scrapes, chunks, and injects fresh regulations into the Global DB."""
        logger.info("Initiating Weekly Global Knowledge Scrape...")
        queries = [
            "Latest RBI master directions digital lending 2026 site:rbi.org.in",
            "Latest GST input tax credit circulars 2026 cbic.gov.in"
        ]
        
        raw_documents = []
        for query in queries:
            try:
                results = self._fetch_regulatory_updates(query)
                for res in results:
                    doc = Document(
                        page_content=res.get("content", ""),
                        metadata={"source": res.get("url", "unknown"), "type": "global_regulation"}
                    )
                    raw_documents.append(doc)
            except Exception as e:
                logger.error(f"Failed to fetch updates for '{query}': {e}")
                raise ScrapingError(f"Scraping failed: {e}")

        if not raw_documents:
            logger.warning("No new updates found. Global DB ingestion skipped.")
            return

        chunks = self.text_splitter.split_documents(raw_documents)
        
        try:
            Chroma.from_documents(
                documents=chunks,
                embedding=self.embeddings,
                persist_directory=self.global_db_dir
            )
            logger.info(f"Successfully injected {len(chunks)} chunks into Global DB.")
        except Exception as e:
            logger.error(f"Failed to update Global DB: {e}")