from __future__ import annotations

import json

import httpx
import pytest


def _events(stream_text: str) -> list[tuple[str, dict]]:
    parsed: list[tuple[str, dict]] = []
    for block in stream_text.strip().split("\n\n"):
        lines = block.splitlines()
        event = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        parsed.append((event, data))
    return parsed


async def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def _auth_headers(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/auth/register",
        json={"name": "テストユーザー", "role": "highschool"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.mark.asyncio
async def test_chat_stream_uses_documented_sse_schema(app) -> None:
    async with await _client(app) as client:
        auth_headers = await _auth_headers(client)
        response = await client.post(
            "/api/chat",
            json={"message": "食堂はどこですか？", "thread_id": None},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = response.text

    events = _events(body)
    assert [event for event, _ in events[:3]] == ["status", "status", "status"]
    assert [payload["step"] for _, payload in events[:3]] == ["analyze", "retrieve", "generate"]
    assert events[0][1]["text"].endswith("…")
    assert any(event == "token" and payload["text"] for event, payload in events)
    assert events[-1][0] == "done"
    assert set(events[-1][1]) == {"thread_id", "message_id", "sources"}
    assert events[-1][1]["sources"][0]["type"] == "web"


@pytest.mark.asyncio
async def test_chat_rejects_unauthorized_request(app) -> None:
    async with await _client(app) as client:
        response = await client.post("/api/chat", json={"message": "こんにちは"})
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_rejects_question_compat_field(app) -> None:
    async with await _client(app) as client:
        auth_headers = await _auth_headers(client)
        response = await client.post(
            "/api/chat",
            json={"question": "食堂はどこですか？"},
            headers=auth_headers,
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_rejects_blank_message(app) -> None:
    async with await _client(app) as client:
        auth_headers = await _auth_headers(client)
        response = await client.post(
            "/api/chat",
            json={"message": "   "},
            headers=auth_headers,
        )
        assert response.status_code == 422
