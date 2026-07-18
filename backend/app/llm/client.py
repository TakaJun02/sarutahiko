from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

ChatMessage = dict[str, str]
TOKENIZE_TIMEOUT_SECONDS = 2.0


class VLLMClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "not-needed",
        timeout_seconds: float = 120.0,
        client: Any | None = None,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self._client = client or self._create_client(api_key=api_key, timeout_seconds=timeout_seconds)

    async def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> AsyncIterator[str]:
        request = self._chat_request(
            messages=messages,
            stream=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        stream = await self._client.chat.completions.create(**request)
        async for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            text = getattr(delta, "content", None)
            if text:
                yield text

    async def complete_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 300,
    ) -> str:
        request = self._chat_request(
            messages=messages,
            stream=False,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        completion = await self._client.chat.completions.create(**request)
        choices = getattr(completion, "choices", None) or []
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        return getattr(message, "content", None) or ""

    async def decide(
        self,
        messages: Sequence[ChatMessage],
        schema: dict[str, Any],
    ) -> str:
        request = self._chat_request(
            messages=messages,
            stream=False,
            temperature=0.2,
            max_tokens=300,
        )
        request["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "react_decision", "schema": schema},
        }
        completion = await self._client.chat.completions.create(**request)
        choices = getattr(completion, "choices", None) or []
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        return getattr(message, "content", None) or ""

    async def count_tokens(self, text: str) -> int | None:
        try:
            async with self._create_tokenize_http_client() as client:
                response = await client.post(
                    self._tokenize_url(),
                    json={"model": self.model, "prompt": text},
                )
        except Exception:
            return None
        if response.status_code < 200 or response.status_code >= 300:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        count = payload.get("count")
        return count if isinstance(count, int) else None

    async def health(self) -> dict:
        await self._client.models.list()
        return {"ok": True, "status": "reachable", "base_url": self.base_url, "model": self.model}

    def _create_client(self, *, api_key: str, timeout_seconds: float) -> Any:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError("openai is required for the real vLLM client") from exc
        return AsyncOpenAI(base_url=self.base_url, api_key=api_key, timeout=timeout_seconds)

    def _create_tokenize_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TOKENIZE_TIMEOUT_SECONDS)

    def _tokenize_url(self) -> str:
        base_url = self.base_url.rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        return f"{base_url}/tokenize"

    def _chat_request(
        self,
        *,
        messages: Sequence[ChatMessage],
        stream: bool,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "stream": stream,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        return request
