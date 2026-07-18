from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.llm.client import TOKENIZE_TIMEOUT_SECONDS, VLLMClient

pytestmark = pytest.mark.asyncio


class FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return self._stream()
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"ok": true}'),
                )
            ]
        )

    async def _stream(self):
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="token"))])


def _fake_openai_client(completions: FakeCompletions):
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


async def test_chat_methods_do_not_send_model_specific_template_kwargs() -> None:
    completions = FakeCompletions()
    client = VLLMClient(
        base_url="http://vllm.test/v1",
        model="google/gemma-4-31B-it-qat-w4a16-ct",
        client=_fake_openai_client(completions),
    )

    await client.complete_chat([{"role": "user", "content": "hello"}])
    tokens = [
        token
        async for token in client.stream_chat(
            [{"role": "user", "content": "hello"}],
        )
    ]

    assert tokens == ["token"]
    assert "extra_body" not in completions.calls[0]
    assert "extra_body" not in completions.calls[1]


async def test_decide_uses_openai_compatible_json_schema_response_format() -> None:
    completions = FakeCompletions()
    client = VLLMClient(
        base_url="http://vllm.test/v1",
        model="google/gemma-4-31B-it-qat-w4a16-ct",
        client=_fake_openai_client(completions),
    )
    schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}},
        "required": ["action"],
    }

    result = await client.decide([{"role": "user", "content": "hello"}], schema)

    assert result == '{"ok": true}'
    assert completions.calls[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "react_decision", "schema": schema},
    }
    assert completions.calls[0]["temperature"] == 0.2
    assert completions.calls[0]["max_tokens"] == 300


async def test_count_tokens_uses_vllm_tokenize_endpoint() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"count": 42})

    client = VLLMClient(
        base_url="http://vllm.test/v1",
        model="google/gemma-4-31B-it-qat-w4a16-ct",
        client=_fake_openai_client(FakeCompletions()),
    )
    client._create_tokenize_http_client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        transport=httpx.MockTransport(handler),
        timeout=TOKENIZE_TIMEOUT_SECONDS,
    )

    count = await client.count_tokens("秋田県立大学")

    assert count == 42
    assert str(requests[0].url) == "http://vllm.test/tokenize"
    assert json.loads(requests[0].content.decode()) == {
        "model": "google/gemma-4-31B-it-qat-w4a16-ct",
        "prompt": "秋田県立大学",
    }


async def test_count_tokens_returns_none_on_tokenize_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("tokenize timeout", request=request)

    client = VLLMClient(
        base_url="http://vllm.test/v1",
        model="google/gemma-4-31B-it-qat-w4a16-ct",
        client=_fake_openai_client(FakeCompletions()),
    )
    client._create_tokenize_http_client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        transport=httpx.MockTransport(handler),
        timeout=TOKENIZE_TIMEOUT_SECONDS,
    )

    assert await client.count_tokens("prompt") is None


async def test_count_tokens_returns_none_on_non_2xx_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    client = VLLMClient(
        base_url="http://vllm.test/v1",
        model="google/gemma-4-31B-it-qat-w4a16-ct",
        client=_fake_openai_client(FakeCompletions()),
    )
    client._create_tokenize_http_client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        transport=httpx.MockTransport(handler),
        timeout=TOKENIZE_TIMEOUT_SECONDS,
    )

    assert await client.count_tokens("prompt") is None
