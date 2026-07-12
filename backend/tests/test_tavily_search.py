from __future__ import annotations

import json

import httpx
import pytest

from app.search.tavily import TAVILY_SEARCH_URL, TavilySearchProvider

pytestmark = pytest.mark.asyncio


def _provider(handler, *, api_key: str = "test-key") -> TavilySearchProvider:
    return TavilySearchProvider(
        api_key=api_key,
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            timeout=8.0,
        ),
    )


async def test_tavily_maps_response_results_and_raw_content() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "公式ページ",
                        "url": "https://www.akita-pu.ac.jp/page",
                        "content": "概要スニペット",
                        "raw_content": "本文全体",
                    },
                    {
                        "title": "URLなし",
                        "content": "skip",
                    },
                ]
            },
        )

    provider = _provider(handler)

    results = await provider.search(
        "秋田県立大学 学長",
        max_results=2,
        include_domains=["akita-pu.ac.jp"],
    )

    assert str(requests[0].url) == TAVILY_SEARCH_URL
    assert requests[0].headers["Authorization"] == "Bearer test-key"
    assert json.loads(requests[0].content.decode()) == {
        "query": "秋田県立大学 学長",
        "max_results": 2,
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": True,
        "include_domains": ["akita-pu.ac.jp"],
    }
    assert len(results) == 1
    assert results[0].title == "公式ページ"
    assert results[0].url == "https://www.akita-pu.ac.jp/page"
    assert results[0].snippet == "概要スニペット"
    assert results[0].text == "本文全体"


async def test_tavily_returns_empty_list_for_api_errors_timeouts_and_missing_key() -> None:
    missing_key_provider = TavilySearchProvider(api_key="")
    assert await missing_key_provider.search("query") == []

    async def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "error"}, request=request)

    assert await _provider(error_handler).search("query") == []

    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    assert await _provider(timeout_handler).search("query") == []

    async def invalid_json_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json", request=request)

    assert await _provider(invalid_json_handler).search("query") == []
