from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from app.search.models import WebSearchResult

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_TIMEOUT_SECONDS = 8.0

logger = logging.getLogger(__name__)


class TavilySearchProvider:
    def __init__(
        self,
        api_key: str,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.client_factory = client_factory or self._default_client

    async def search(
        self,
        query: str,
        *,
        max_results: int = 3,
        include_domains: Sequence[str] | None = None,
    ) -> list[WebSearchResult]:
        if not self.api_key:
            logger.warning("Tavily search skipped because TAVILY_API_KEY is not configured")
            return []

        payload: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": True,
        }
        if include_domains:
            payload["include_domains"] = list(include_domains)

        try:
            async with self.client_factory() as client:
                response = await client.post(
                    TAVILY_SEARCH_URL,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("Tavily search returned HTTP %s", exc.response.status_code)
            return []
        except httpx.TimeoutException:
            logger.warning("Tavily search timed out")
            return []
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Tavily search failed: %s", exc.__class__.__name__)
            return []

        rows = data.get("results") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            logger.warning("Tavily search returned an invalid response shape")
            return []

        results: list[WebSearchResult] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            if not url:
                continue
            title = str(row.get("title") or url)
            snippet = str(row.get("content") or row.get("snippet") or "")
            raw_content = row.get("raw_content")
            results.append(
                WebSearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    text=raw_content if isinstance(raw_content, str) else "",
                )
            )
            if len(results) >= max_results:
                break
        return results

    @staticmethod
    def _default_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TAVILY_TIMEOUT_SECONDS)
