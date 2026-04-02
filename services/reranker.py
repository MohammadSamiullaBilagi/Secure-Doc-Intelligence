"""
Reranker service — uses Gemini Flash to score and filter retrieved chunks by relevance.

After ChromaDB similarity search returns k chunks, the reranker scores each chunk
against the specific query and returns only the top_k most relevant ones.
Gracefully falls back to returning original documents on any error.
"""

import json
import logging
from typing import List

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

RERANK_SYSTEM_PROMPT = """You are a relevance scoring specialist.

Given a QUERY and a list of text CHUNKS, score each chunk from 1 to 10 based on how relevant it is to answering the query.

SCORING GUIDE:
- 10: Directly answers the query with specific data/values
- 7-9: Contains highly relevant information (dates, amounts, names, sections)
- 4-6: Partially relevant or provides background context
- 1-3: Irrelevant or only tangentially related

OUTPUT: Return VALID JSON ONLY — an array of objects:
[{"index": 0, "score": 8}, {"index": 1, "score": 3}, ...]

Return scores for ALL chunks. Do NOT skip any index."""

RERANK_HUMAN_PROMPT = """QUERY: {query}

CHUNKS:
{chunks}

Score each chunk and return the JSON array:"""


async def rerank_documents(
    query: str,
    documents: List[Document],
    top_k: int = 10,
) -> List[Document]:
    """Rerank documents by relevance to query using Gemini Flash.

    Args:
        query: The specific question or check focus
        documents: Retrieved chunks from ChromaDB
        top_k: Number of top-scoring chunks to return

    Returns:
        Reranked and filtered list of Documents (top_k most relevant)
    """
    if not documents or len(documents) <= top_k:
        return documents

    try:
        from services.llm_config import get_json_llm

        llm = get_json_llm(heavy=False)  # Gemini Flash for speed

        # Format chunks with index labels
        chunks_text = "\n\n".join(
            f"[CHUNK {i}]: {doc.page_content[:500]}"
            for i, doc in enumerate(documents)
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", RERANK_SYSTEM_PROMPT),
            ("human", RERANK_HUMAN_PROMPT),
        ])

        response = await (prompt | llm).ainvoke({
            "query": query,
            "chunks": chunks_text,
        })

        # Parse scores
        content = response.content if hasattr(response, "content") else str(response)
        scores = json.loads(content)

        # Sort by score descending and pick top_k
        scores.sort(key=lambda x: x.get("score", 0), reverse=True)
        top_indices = [s["index"] for s in scores[:top_k] if s["index"] < len(documents)]

        reranked = [documents[i] for i in top_indices]
        logger.info(f"Reranker: {len(documents)} chunks → {len(reranked)} (top {top_k})")
        return reranked

    except Exception as e:
        logger.warning(f"Reranker failed, returning original documents: {e}")
        return documents[:top_k]


def rerank_documents_sync(
    query: str,
    documents: List[Document],
    top_k: int = 10,
) -> List[Document]:
    """Synchronous wrapper for reranking — used in LangGraph nodes that run synchronously."""
    import asyncio

    if not documents or len(documents) <= top_k:
        return documents

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, rerank_documents(query, documents, top_k))
            return future.result()
    else:
        return asyncio.run(rerank_documents(query, documents, top_k))
