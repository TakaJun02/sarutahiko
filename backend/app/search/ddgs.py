from __future__ import annotations

import asyncio
from typing import Any

from app.search.models import WebSearchResult


class DDGSSearchProvider:
    def __init__(self, client_factory: Any | None = None) -> None:
        self._client_factory = client_factory

    async def search(self, query: str, *, max_results: int = 3) -> list[WebSearchResult]:
        return await asyncio.to_thread(self._search_sync, query, max_results)

    def _search_sync(self, query: str, max_results: int) -> list[WebSearchResult]:
        factory = self._client_factory or self._load_ddgs
        client = factory()
        if hasattr(client, "__enter__"):
            with client as active_client:
                rows = active_client.text(query, max_results=max_results)
        else:
            try:
                rows = client.text(query, max_results=max_results)
            finally:
                close = getattr(client, "close", None)
                if close is not None:
                    close()
        results: list[WebSearchResult] = []
        for row in rows:
            url = row.get("href") or row.get("url") or ""
            if not url:
                continue
            results.append(
                WebSearchResult(
                    title=row.get("title") or url,
                    url=url,
                    snippet=row.get("body") or row.get("snippet") or "",
                )
            )
        return results[:max_results]

    @staticmethod
    def _load_ddgs() -> Any:
        try:
            from ddgs import DDGS
        except ImportError as exc:
            raise RuntimeError("ddgs is required for web search") from exc
        return DDGS()
