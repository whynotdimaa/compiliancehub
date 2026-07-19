"""Tavily web search — the CRAG fallback for questions the tenant's documents
cannot answer (e.g. a regulation newer than anything ingested).

Optional and fail-safe: no API key -> empty results; any HTTP/parse error ->
empty results with a warning. Web search is a bonus signal, never a
dependency of /ask availability.
"""
from dataclasses import dataclass

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger()

TAVILY_URL = "https://api.tavily.com/search"


@dataclass
class WebResult:
    title: str
    url: str
    content: str


async def tavily_search(query: str) -> list[WebResult]:
    if not settings.tavily_api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                TAVILY_URL,
                json={
                    "api_key": settings.tavily_api_key,
                    "query": query,
                    "max_results": settings.tavily_max_results,
                    "search_depth": "basic",
                },
            )
        response.raise_for_status()
        results = response.json().get("results", [])
    except Exception as exc:
        logger.warning("tavily_search_failed", error=str(exc))
        return []
    return [
        WebResult(
            title=str(item.get("title", ""))[:300],
            url=str(item.get("url", "")),
            content=str(item.get("content", ""))[:2000],
        )
        for item in results
        if isinstance(item, dict) and item.get("content")
    ]
