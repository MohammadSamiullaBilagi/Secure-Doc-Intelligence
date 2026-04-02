"""
Central LLM configuration — single source of truth for all model instances.

Two tiers:
  - Heavy (Gemini 2.5 Pro): extraction, compliance evaluation, drafting
  - Light (Gemini 2.0 Flash): routing, reranking, query expansion

Falls back to OpenAI gpt-4o-mini if GOOGLE_API_KEY is not set.
Embeddings always use OpenAI text-embedding-3-small (unchanged).
"""

import logging
from functools import lru_cache

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _google_api_available() -> bool:
    """Check if Google API key is configured."""
    from config import settings
    available = bool(settings.GOOGLE_API_KEY)
    if available:
        logger.info("GOOGLE_API_KEY found — using Gemini models")
    else:
        logger.warning("GOOGLE_API_KEY not set — falling back to OpenAI gpt-4o-mini")
    return available


def _get_gemini_chat(model: str, temperature: float = 0, max_tokens: int | None = None):
    """Create a ChatGoogleGenerativeAI instance."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    from config import settings

    kwargs = {
        "model": model,
        "temperature": temperature,
        "google_api_key": settings.GOOGLE_API_KEY,
    }
    if max_tokens:
        kwargs["max_output_tokens"] = max_tokens
    return ChatGoogleGenerativeAI(**kwargs)


def _get_openai_chat(temperature: float = 0, max_tokens: int | None = None):
    """Fallback: OpenAI gpt-4o-mini."""
    kwargs = {"model": "gpt-4o-mini", "temperature": temperature}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    return ChatOpenAI(**kwargs)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_heavy_llm(temperature: float = 0, max_tokens: int | None = None):
    """Gemini 2.5 Pro for accuracy-critical tasks (extraction, evaluation, drafting).

    Falls back to gpt-4o-mini if GOOGLE_API_KEY is not set.
    """
    if _google_api_available():
        return _get_gemini_chat("gemini-2.5-pro", temperature, max_tokens)
    return _get_openai_chat(temperature, max_tokens)


def get_light_llm(temperature: float = 0, max_tokens: int | None = None):
    """Gemini 2.0 Flash for lightweight tasks (routing, reranking, query expansion).

    Falls back to gpt-4o-mini if GOOGLE_API_KEY is not set.
    """
    if _google_api_available():
        return _get_gemini_chat("gemini-2.0-flash", temperature, max_tokens)
    return _get_openai_chat(temperature, max_tokens)


def get_json_llm(heavy: bool = True, temperature: float = 0, max_tokens: int | None = None):
    """LLM configured for JSON output.

    For Gemini: uses response_mime_type="application/json"
    For OpenAI fallback: uses response_format={"type": "json_object"}
    """
    if _google_api_available():
        from langchain_google_genai import ChatGoogleGenerativeAI
        from config import settings

        model = "gemini-2.5-pro" if heavy else "gemini-2.0-flash"
        kwargs = {
            "model": model,
            "temperature": temperature,
            "google_api_key": settings.GOOGLE_API_KEY,
            "model_kwargs": {"response_mime_type": "application/json"},
        }
        if max_tokens:
            kwargs["max_output_tokens"] = max_tokens
        return ChatGoogleGenerativeAI(**kwargs)

    # OpenAI fallback with JSON mode
    kwargs = {"model": "gpt-4o-mini", "temperature": temperature}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    return ChatOpenAI(**kwargs).bind(response_format={"type": "json_object"})


def get_embeddings():
    """OpenAI embeddings — always text-embedding-3-small (unchanged)."""
    return OpenAIEmbeddings(model="text-embedding-3-small")
