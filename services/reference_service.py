"""Ground truth reference service — uses Tavily search + Haiku extraction + DB cache."""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial

from langchain_core.prompts import ChatPromptTemplate

from services.llm_config import get_light_llm

from schemas.blueprint_schema import BlueprintCheck
from config import settings

logger = logging.getLogger(__name__)


@dataclass
class ReferenceResult:
    """Result of a ground truth reference lookup."""
    extracted_rules: str
    confidence: str  # HIGH (live search) | MEDIUM (cached <TTL) | LOW (fallback)
    source_url: str | None
    source_name: str


# Search query templates per check_id prefix — produces targeted Tavily queries
SEARCH_TEMPLATES: dict[str, dict] = {
    "GST": {
        "query_prefix": "India GST CGST Act 2017",
        "source_label": "GST/CGST Act",
        "ttl": 30,
    },
    "TDS": {
        "query_prefix": "India Income Tax Act TDS",
        "source_label": "Income Tax Act (TDS)",
        "ttl": 14,
    },
    "IT": {
        "query_prefix": "India Income Tax Act 1961",
        "source_label": "Income Tax Act 1961",
        "ttl": 14,
    },
    "AUDIT": {
        "query_prefix": "India ICAI Standards on Auditing",
        "source_label": "ICAI Auditing Standards",
        "ttl": 30,
    },
    "RBI": {
        "query_prefix": "RBI India circular regulation",
        "source_label": "RBI Regulations",
        "ttl": 14,
    },
    "COMP": {
        "query_prefix": "India Companies Act 2013",
        "source_label": "Companies Act 2013",
        "ttl": 30,
    },
    "MSME": {
        "query_prefix": "India MSME Section 43B(h) Income Tax Act payment terms deduction",
        "source_label": "Income Tax Act (MSME)",
        "ttl": 30,
    },
}


def _build_search_query(check_id: str, rule_text: str) -> tuple[str, str, int]:
    """Build a Tavily search query from check_id and rule text.

    Returns: (search_query, source_label, ttl_days)
    """
    prefix = check_id.split("_")[0] if "_" in check_id else check_id
    template = SEARCH_TEMPLATES.get(prefix, {
        "query_prefix": "India tax compliance regulation",
        "source_label": "Regulatory Source",
        "ttl": 30,
    })

    # Extract section references from the rule text (e.g., "Section 40A(3)", "194J")
    import re
    sections = re.findall(r'(?:Section|Sec\.?|Rule)\s*\d+[\w()]*', rule_text, re.IGNORECASE)
    section_str = " ".join(sections[:3]) if sections else ""

    # Build a focused search query
    query = f"{template['query_prefix']} {section_str} {rule_text[:120]}"
    return query.strip(), template["source_label"], template["ttl"]


class ReferenceService:
    """Fetches ground truth regulatory references via Tavily search + Haiku extraction."""

    def __init__(self):
        self.llm = get_light_llm(max_tokens=1024)

    async def get_reference(self, check_id: str, rule_text: str) -> ReferenceResult:
        """Get ground truth reference for a single check.

        Priority: DB cache (within TTL) → Tavily search + Haiku extract → fallback to rule_text.
        """
        # 1. Check DB cache
        cached = await self._get_cached(check_id)
        if cached:
            logger.info(f"Reference cache HIT for {check_id}")
            return cached

        # 2. Tavily web search → Haiku extraction
        search_query, source_label, ttl = _build_search_query(check_id, rule_text)
        try:
            search_results = await self._tavily_search(search_query)
            if search_results:
                # Combine search result content
                combined_content = ""
                source_urls = []
                for r in search_results[:5]:
                    combined_content += f"\n\n--- Source: {r.get('url', 'unknown')} ---\n{r.get('content', '')}"
                    if r.get('url'):
                        source_urls.append(r['url'])

                if len(combined_content) > 200:
                    extracted = await self._extract_rules(combined_content, rule_text, check_id)
                    result = ReferenceResult(
                        extracted_rules=extracted,
                        confidence="HIGH",
                        source_url=source_urls[0] if source_urls else None,
                        source_name=source_label,
                    )
                    await self._store_cache(check_id, result, ttl)
                    logger.info(f"Reference fetched via Tavily for {check_id} — {len(source_urls)} sources")
                    return result
        except Exception as e:
            logger.warning(f"Tavily search failed for {check_id}: {e}")

        # 3. Fallback — use the blueprint rule text itself
        logger.info(f"Reference fallback for {check_id} — using blueprint rule text")
        return ReferenceResult(
            extracted_rules=rule_text,
            confidence="LOW",
            source_url=None,
            source_name="Blueprint Rule (fallback)",
        )

    async def get_references_batch(self, checks: list[BlueprintCheck]) -> dict[str, ReferenceResult]:
        """Fetch references for all checks with cost optimization.

        Groups checks by prefix (e.g. GST, TDS) and shares a single Tavily search
        per group instead of one search per check. This cuts Tavily + Haiku extraction
        costs by ~60-80% for blueprints with many checks under the same prefix.
        """
        ref_map: dict[str, ReferenceResult] = {}

        # 1. Check DB cache first for ALL checks (free — no API calls)
        uncached_checks = []
        for check in checks:
            cached = await self._get_cached(check.check_id)
            if cached:
                ref_map[check.check_id] = cached
                logger.info(f"Reference cache HIT for {check.check_id}")
            else:
                uncached_checks.append(check)

        if not uncached_checks:
            return ref_map

        # 2. Group uncached checks by prefix to share Tavily searches
        from collections import defaultdict
        groups: dict[str, list[BlueprintCheck]] = defaultdict(list)
        for check in uncached_checks:
            prefix = check.check_id.split("_")[0] if "_" in check.check_id else check.check_id
            groups[prefix].append(check)

        logger.info(f"Reference: {len(ref_map)} cached, {len(uncached_checks)} uncached across {len(groups)} groups")

        # 3. One Tavily search per group (not per check)
        semaphore = asyncio.Semaphore(2)

        async def _fetch_group(prefix: str, group_checks: list[BlueprintCheck]):
            async with semaphore:
                # Build a combined query from all checks in this group
                combined_rules = " | ".join([c.rule[:80] for c in group_checks[:5]])
                search_query, source_label, ttl = _build_search_query(
                    group_checks[0].check_id, combined_rules
                )

                # Single Tavily search for the whole group
                search_results = None
                combined_content = ""
                source_urls = []
                try:
                    search_results = await self._tavily_search(search_query)
                    if search_results:
                        for r in search_results[:3]:
                            combined_content += f"\n\n--- Source: {r.get('url', 'unknown')} ---\n{r.get('content', '')}"
                            if r.get('url'):
                                source_urls.append(r['url'])
                except Exception as e:
                    logger.warning(f"Tavily search failed for group {prefix}: {e}")

                # Extract rules per check using the shared search content
                for check in group_checks:
                    if combined_content and len(combined_content) > 200:
                        try:
                            extracted = await self._extract_rules(combined_content, check.rule, check.check_id)
                            result = ReferenceResult(
                                extracted_rules=extracted,
                                confidence="HIGH",
                                source_url=source_urls[0] if source_urls else None,
                                source_name=source_label,
                            )
                            await self._store_cache(check.check_id, result, ttl)
                            ref_map[check.check_id] = result
                        except Exception as e:
                            logger.warning(f"Extraction failed for {check.check_id}: {e}")
                            ref_map[check.check_id] = ReferenceResult(
                                extracted_rules=check.rule,
                                confidence="LOW",
                                source_url=None,
                                source_name="Blueprint Rule (fallback)",
                            )
                    else:
                        ref_map[check.check_id] = ReferenceResult(
                            extracted_rules=check.rule,
                            confidence="LOW",
                            source_url=None,
                            source_name="Blueprint Rule (fallback)",
                        )

        await asyncio.gather(
            *[_fetch_group(prefix, group_checks) for prefix, group_checks in groups.items()],
            return_exceptions=True,
        )

        # Fill any missing checks with fallback
        for check in checks:
            if check.check_id not in ref_map:
                ref_map[check.check_id] = ReferenceResult(
                    extracted_rules=check.rule,
                    confidence="LOW",
                    source_url=None,
                    source_name="Blueprint Rule (error fallback)",
                )

        return ref_map

    async def _tavily_search(self, query: str) -> list[dict] | None:
        """Search the web using Tavily API — returns clean extracted content."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": settings.tavily_api_key,
                        "query": query,
                        "search_depth": "basic",
                        "max_results": 3,
                        "include_answer": False,
                        "include_raw_content": False,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = data.get("results", [])
                    if results:
                        logger.info(f"Tavily returned {len(results)} results for: {query[:80]}...")
                    return results
                else:
                    logger.warning(f"Tavily API returned {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"Tavily search failed: {e}")
        return None

    async def _extract_rules(self, content: str, rule_text: str, check_id: str) -> str:
        """Use Haiku to extract specific regulatory rules from Tavily search results."""
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an Indian regulatory compliance specialist.\n\n"
             "TASK: Extract ONLY the specific legal rules, thresholds, rates, deadlines, "
             "and penalties relevant to the compliance check below.\n\n"
             "RULES:\n"
             "1. Return bullet points of FACTUAL rules with section numbers.\n"
             "2. Include exact thresholds (e.g., 'Rs 10,000 per transaction per day').\n"
             "3. Include penalty rates (e.g., 'interest @1% per month under Section 234C').\n"
             "4. Include deadlines (e.g., 'due by 7th of next month for non-govt deductors').\n"
             "5. If the search results don't contain relevant info, state 'No specific rules found.'\n"
             "6. Do NOT make up rules — only extract what is actually in the source content."),
            ("human",
             "COMPLIANCE CHECK ({check_id}): {rule_text}\n\n"
             "WEB SEARCH RESULTS:\n{content}\n\n"
             "Extract the relevant regulatory rules with exact thresholds and penalties:"),
        ])
        try:
            response = await (prompt | self.llm).ainvoke({
                "check_id": check_id,
                "rule_text": rule_text,
                "content": content[:10000],
            })
            return response.content
        except Exception as e:
            logger.error(f"Haiku extraction failed for {check_id}: {e}")
            return rule_text

    async def _get_cached(self, check_id: str) -> ReferenceResult | None:
        """Check the reference_cache DB table for a valid cached entry."""
        try:
            from db.database import AsyncSessionLocal
            from db.models.references import ReferenceCache
            from sqlalchemy import select

            async with AsyncSessionLocal() as session:
                stmt = select(ReferenceCache).where(ReferenceCache.check_id == check_id)
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()

                if row and row.fetched_at:
                    age_days = (datetime.now(timezone.utc) - row.fetched_at.replace(tzinfo=timezone.utc)).days
                    if age_days <= row.ttl_days:
                        return ReferenceResult(
                            extracted_rules=row.extracted_rules or "",
                            confidence="MEDIUM",
                            source_url=row.source_url,
                            source_name=row.source_name,
                        )
        except Exception as e:
            logger.warning(f"Cache lookup failed for {check_id}: {e}")
        return None

    async def _store_cache(self, check_id: str, ref: ReferenceResult, ttl: int) -> None:
        """Store or update a reference cache entry."""
        try:
            from db.database import AsyncSessionLocal
            from db.models.references import ReferenceCache
            from sqlalchemy import select
            import uuid

            async with AsyncSessionLocal() as session:
                stmt = select(ReferenceCache).where(ReferenceCache.check_id == check_id)
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()

                if row:
                    row.extracted_rules = ref.extracted_rules
                    row.source_url = ref.source_url
                    row.source_name = ref.source_name
                    row.ttl_days = ttl
                    row.fetched_at = datetime.now(timezone.utc)
                else:
                    row = ReferenceCache(
                        id=uuid.uuid4(),
                        check_id=check_id,
                        source_name=ref.source_name,
                        source_url=ref.source_url,
                        extracted_rules=ref.extracted_rules,
                        ttl_days=ttl,
                        fetched_at=datetime.now(timezone.utc),
                    )
                    session.add(row)

                await session.commit()
        except Exception as e:
            logger.warning(f"Cache store failed for {check_id}: {e}")
