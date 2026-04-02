"""
Query expander — generates multiple targeted retrieval queries for compliance checks.

Instead of using a single generic query to retrieve document chunks, this service
generates 3 specific search queries tailored to each compliance check's focus and rule.
This improves retrieval recall for the L2 CheckAgentService.
"""

import json
import logging
from typing import List

from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

EXPAND_SYSTEM_PROMPT = """You are a search query specialist for Indian tax and legal compliance documents.

Given a compliance CHECK with a focus area and rule, generate exactly 3 targeted search queries
that would help find the relevant information in a financial/legal document.

Each query should target DIFFERENT aspects of the check:
1. One query for the specific data points (amounts, dates, names, GSTINs)
2. One query for the compliance requirement (section references, rules, thresholds)
3. One query for supporting evidence (calculations, breakdowns, tables)

OUTPUT: Return VALID JSON ONLY — an array of 3 strings:
["query 1", "query 2", "query 3"]"""

EXPAND_HUMAN_PROMPT = """COMPLIANCE CHECK ({check_id}):
  Focus: {focus}
  Rule: {rule}

Generate 3 targeted search queries:"""


async def expand_query(check_id: str, focus: str, rule: str) -> List[str]:
    """Generate 3 targeted retrieval queries for a compliance check.

    Args:
        check_id: The check identifier (e.g., "GST_01")
        focus: What the check focuses on (e.g., "GSTIN validation")
        rule: The compliance rule being checked

    Returns:
        List of 3 search query strings. Falls back to [focus] on error.
    """
    try:
        from services.llm_config import get_json_llm

        llm = get_json_llm(heavy=False)  # Gemini Flash for speed

        prompt = ChatPromptTemplate.from_messages([
            ("system", EXPAND_SYSTEM_PROMPT),
            ("human", EXPAND_HUMAN_PROMPT),
        ])

        response = await (prompt | llm).ainvoke({
            "check_id": check_id,
            "focus": focus,
            "rule": rule,
        })

        content = response.content if hasattr(response, "content") else str(response)
        queries = json.loads(content)

        if isinstance(queries, list) and len(queries) >= 1:
            logger.info(f"Query expansion for {check_id}: {len(queries)} queries generated")
            return queries[:3]

        return [focus]

    except Exception as e:
        logger.warning(f"Query expansion failed for {check_id}, using focus as fallback: {e}")
        return [focus]
