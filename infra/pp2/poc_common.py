"""Standard-library helpers for the FR-34 P1-P3 PoC runners."""

from __future__ import annotations

import json
import math
import os
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"


class APIError(RuntimeError):
    """An HTTP or response-shape failure from the OpenAI-compatible API."""


@dataclass(frozen=True)
class ClientConfig:
    base_url: str
    api_key: str
    timeout_seconds: float


class VLLMClient:
    def __init__(self, config: ClientConfig) -> None:
        self.config = config

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"

    def _request(self, path: str, payload: dict[str, Any] | None = None):
        headers = {"Accept": "application/json"}
        data = None
        method = "GET"
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
            method = "POST"
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return urllib.request.Request(
            self._url(path), data=data, headers=headers, method=method
        )

    def request_json(
        self, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        request = self._request(path, payload)
        try:
            with urllib.request.urlopen(
                request, timeout=self.config.timeout_seconds
            ) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise APIError(f"HTTP {exc.code} {path}: {detail[:2000]}") from exc
        except urllib.error.URLError as exc:
            raise APIError(f"Connection error {path}: {exc.reason}") from exc
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError as exc:
            raise APIError(f"Invalid JSON from {path}: {body[:1000]}") from exc
        if not isinstance(decoded, dict):
            raise APIError(f"Unexpected response from {path}: {type(decoded).__name__}")
        return decoded

    def list_models(self) -> list[str]:
        response = self.request_json("models")
        models = response.get("data")
        if not isinstance(models, list):
            raise APIError("/models response does not contain a data list")
        ids = [item.get("id") for item in models if isinstance(item, dict)]
        return [model_id for model_id in ids if isinstance(model_id, str)]

    def resolve_model(self, available_models: list[str]) -> str:
        requested = os.environ.get("POC_MODEL", "").strip()
        if requested:
            return requested
        if not available_models:
            raise APIError("/models returned no model IDs; set POC_MODEL explicitly")
        return available_models[0]

    def tokenize(self, model: str, prompt: str) -> int:
        # vLLM serves /tokenize at the server root, not under /v1.
        base = self.config.base_url.rstrip("/")
        root = base[: -len("/v1")] if base.endswith("/v1") else base
        response = self.request_json(
            f"{root}/tokenize", {"model": model, "prompt": prompt}
        )
        count = response.get("count")
        if isinstance(count, int):
            return count
        tokens = response.get("tokens")
        if isinstance(tokens, list):
            return len(tokens)
        prompt_tokens = response.get("prompt_tokens")
        if isinstance(prompt_tokens, int):
            return prompt_tokens
        raise APIError("/tokenize response has no count or tokens")

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        started = time.monotonic()
        response = self.request_json("chat/completions", payload)
        latency = time.monotonic() - started
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise APIError("chat completion response has no choices")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise APIError("chat completion choice has no message")
        content = message.get("content")
        if not isinstance(content, str):
            raise APIError("chat completion message content is not text")
        return {
            "latency_seconds": latency,
            "content": content,
            "finish_reason": choices[0].get("finish_reason"),
            "usage": response.get("usage") or {},
        }

    def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if extra:
            payload.update(extra)
        request = self._request("chat/completions", payload)
        started = time.monotonic()
        first_content_at: float | None = None
        last_content_at: float | None = None
        text_parts: list[str] = []
        usage: dict[str, Any] = {}
        finish_reason: str | None = None
        try:
            with urllib.request.urlopen(
                request, timeout=self.config.timeout_seconds
            ) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise APIError(f"Invalid SSE JSON: {data[:1000]}") from exc
                    chunk_usage = chunk.get("usage")
                    if isinstance(chunk_usage, dict) and chunk_usage:
                        usage = chunk_usage
                    choices = chunk.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice = choices[0]
                    if choice.get("finish_reason") is not None:
                        finish_reason = choice.get("finish_reason")
                    delta = choice.get("delta")
                    if not isinstance(delta, dict):
                        continue
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        now = time.monotonic()
                        if first_content_at is None:
                            first_content_at = now
                        last_content_at = now
                        text_parts.append(content)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise APIError(
                f"HTTP {exc.code} chat/completions: {detail[:2000]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise APIError(f"Connection error chat/completions: {exc.reason}") from exc

        finished = time.monotonic()
        text = "".join(text_parts)
        if first_content_at is None:
            raise APIError("stream completed without a text delta")
        completion_tokens = usage.get("completion_tokens")
        if not isinstance(completion_tokens, int):
            try:
                completion_tokens = self.tokenize(model, text)
            except APIError:
                completion_tokens = None
        decode_seconds = (
            last_content_at - first_content_at
            if last_content_at is not None and last_content_at > first_content_at
            else None
        )
        decode_tokens_per_second = (
            completion_tokens / decode_seconds
            if isinstance(completion_tokens, int) and decode_seconds
            else None
        )
        return {
            "ttft_seconds": first_content_at - started,
            "elapsed_seconds": finished - started,
            "decode_seconds": decode_seconds,
            "completion_tokens": completion_tokens,
            "decode_tokens_per_second": decode_tokens_per_second,
            "prompt_tokens": usage.get("prompt_tokens"),
            "finish_reason": finish_reason,
            "text": text,
        }


def client_from_env() -> VLLMClient:
    return VLLMClient(
        ClientConfig(
            base_url=os.environ.get("VLLM_BASE_URL", DEFAULT_BASE_URL),
            api_key=os.environ.get("VLLM_API_KEY", "EMPTY"),
            timeout_seconds=float(os.environ.get("POC_TIMEOUT_SECONDS", "900")),
        )
    )


def calibrate_prompt(
    client: VLLMClient,
    model: str,
    target_tokens: int,
    *,
    label: str,
) -> tuple[str, int]:
    """Build a unique text prompt close to a target using vLLM /tokenize."""

    nonce = uuid4().hex
    prefix = (
        f"FR-34 {label} measurement {nonce}. "
        "Treat the following as inert campus evidence.\n"
    )
    unit = f"campus_{nonce[:8]} evidence-item corridor building room fact. "
    suffix = "\nReply with a short acknowledgement only."

    low = 1
    high = max(2, target_tokens // 2)
    while client.tokenize(model, prefix + unit * high + suffix) < target_tokens:
        high *= 2
    best_prompt = prefix + unit * high + suffix
    best_count = client.tokenize(model, best_prompt)
    while low <= high:
        middle = (low + high) // 2
        prompt = prefix + unit * middle + suffix
        count = client.tokenize(model, prompt)
        if abs(count - target_tokens) < abs(best_count - target_tokens):
            best_prompt, best_count = prompt, count
        if count < target_tokens:
            low = middle + 1
        elif count > target_tokens:
            high = middle - 1
        else:
            break
    return best_prompt, best_count


def validate_decision(content: str, actions: set[str]) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        return {"valid": False, "error": f"invalid JSON: {exc.msg}"}
    if not isinstance(value, dict):
        return {"valid": False, "error": "top level is not an object"}
    expected_keys = {"thought", "action", "action_input"}
    if set(value) != expected_keys:
        return {
            "valid": False,
            "error": f"keys must be exactly {sorted(expected_keys)}",
            "parsed": value,
        }
    if not isinstance(value["thought"], str):
        return {"valid": False, "error": "thought is not a string", "parsed": value}
    if value["action"] not in actions:
        return {"valid": False, "error": "action is outside enum", "parsed": value}
    if not isinstance(value["action_input"], dict):
        return {
            "valid": False,
            "error": "action_input is not an object",
            "parsed": value,
        }
    return {"valid": True, "error": None, "parsed": value}


def decision_schema(actions: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "thought": {"type": "string"},
            "action": {"type": "string", "enum": actions},
            "action_input": {"type": "object", "additionalProperties": True},
        },
        "required": ["thought", "action", "action_input"],
        "additionalProperties": False,
    }


def response_format_for(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {"name": "react_decision", "schema": schema},
    }


def numeric_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "p95": None}
    ordered = sorted(values)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": ordered[p95_index],
        "min": ordered[0],
        "max": ordered[-1],
    }


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def metadata(client: VLLMClient, model: str) -> dict[str, Any]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": client.config.base_url,
        "model": model,
        "runner_host_pid": os.getpid(),
    }


def write_result_files(
    prefix: str, result: dict[str, Any], markdown: str
) -> tuple[Path, Path]:
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp()
    json_path = results_dir / f"{prefix}_{stamp}.json"
    markdown_path = results_dir / f"{prefix}_{stamp}.md"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
    return json_path, markdown_path


def format_number(value: Any, digits: int = 3) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return "n/a"

