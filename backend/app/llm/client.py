from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

ChatMessage = dict[str, str]


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
        enable_thinking: bool = False,
    ) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=list(messages),
            stream=True,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": enable_thinking}},
        )
        async for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            text = getattr(delta, "content", None)
            if text:
                yield text

    async def health(self) -> dict:
        await self._client.models.list()
        return {"ok": True, "status": "reachable", "base_url": self.base_url, "model": self.model}

    def _create_client(self, *, api_key: str, timeout_seconds: float) -> Any:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError("openai is required for the real vLLM client") from exc
        return AsyncOpenAI(base_url=self.base_url, api_key=api_key, timeout=timeout_seconds)
