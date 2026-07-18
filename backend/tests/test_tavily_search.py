from __future__ import annotations

import json
import time

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


async def test_tavily_can_suppress_raw_content_for_soft_budget() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"results": []})

    provider = _provider(handler)

    await provider.search(
        "秋田県立大学",
        include_raw_content=False,
    )

    payload = json.loads(requests[0].content.decode())
    assert payload["include_raw_content"] is False
    assert "include_domains" not in payload


async def test_tavily_opens_circuit_after_432_and_skips_requests_during_cooldown(caplog) -> None:
    factory_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(432, json={"detail": "quota exceeded"}, request=request)

    def client_factory() -> httpx.AsyncClient:
        nonlocal factory_calls
        factory_calls += 1
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=8.0)

    provider = TavilySearchProvider(api_key="test-key", client_factory=client_factory)

    assert await provider.search("first query") == []
    assert provider.available is False
    assert await provider.search("second query") == []
    assert factory_calls == 1
    assert any("HTTP 432" in record.message and "600" in record.message for record in caplog.records)


async def test_tavily_reprobes_after_cooldown_expires() -> None:
    factory_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        if factory_calls == 1:
            return httpx.Response(432, json={"detail": "quota exceeded"}, request=request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Recovered",
                        "url": "https://example.test/recovered",
                        "content": "available again",
                    }
                ]
            },
            request=request,
        )

    def client_factory() -> httpx.AsyncClient:
        nonlocal factory_calls
        factory_calls += 1
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=8.0)

    provider = TavilySearchProvider(api_key="test-key", client_factory=client_factory)

    assert await provider.search("first query") == []
    provider.unavailable_until = time.monotonic() - 1
    results = await provider.search("retry query")

    assert factory_calls == 2
    assert provider.available is True
    assert [result.title for result in results] == ["Recovered"]


async def test_tavily_transient_errors_do_not_open_circuit() -> None:

    async def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "error"}, request=request)

    server_error_provider = _provider(error_handler)
    assert await server_error_provider.search("query") == []
    assert server_error_provider.available is True

    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    timeout_provider = _provider(timeout_handler)
    assert await timeout_provider.search("query") == []
    assert timeout_provider.available is True


async def test_tavily_missing_key_is_unavailable() -> None:
    missing_key_provider = TavilySearchProvider(api_key="")

    assert missing_key_provider.available is False
    assert await missing_key_provider.search("query") == []


async def test_tavily_returns_empty_list_for_invalid_json() -> None:

    async def invalid_json_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json", request=request)

    assert await _provider(invalid_json_handler).search("query") == []
