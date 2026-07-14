from __future__ import annotations

import json

import httpx
import pytest

from app.models.auth import User


class RecordingAgent:
    def __init__(self) -> None:
        self.history: list[dict] | None = None

    async def stream(self, question, user, thread_id, message_id, history=None):
        self.history = history
        yield "token", {"text": "記録済み"}
        yield "done", {"thread_id": thread_id, "message_id": message_id, "sources": []}

    @staticmethod
    def format_sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


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
        json={"name": "テストユーザー"},
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
    assert [event for event, _ in events[:4]] == ["status", "status", "status", "status"]
    assert [payload["step"] for _, payload in events[:4]] == ["analyze", "retrieve", "search", "generate"]
    assert events[0][1]["text"].endswith("…")
    assert any(event == "token" and payload["text"] for event, payload in events)
    assert events[-1][0] == "done"
    assert set(events[-1][1]) == {"thread_id", "message_id", "sources"}
    assert events[-1][1]["sources"][0]["type"] == "web"


@pytest.mark.asyncio
async def test_chat_passes_latest_eight_stored_messages_in_chronological_order(app) -> None:
    recording_agent = RecordingAgent()
    app.state.agent = recording_agent

    async with await _client(app) as client:
        register = await client.post("/api/auth/register", json={"name": "履歴テスト"})
        assert register.status_code == 201
        auth = register.json()
        headers = {"Authorization": f"Bearer {auth['token']}"}
        user = User(**auth["user"])
        thread_id = app.state.thread_service.ensure_thread(user, None, "message-0")

        message_ids = [
            app.state.thread_service.add_message(
                thread_id,
                "user" if index % 2 == 0 else "assistant",
                f"message-{index}",
            )
            for index in range(10)
        ]
        with app.state.database.connect() as connection:
            for index, message_id in enumerate(message_ids):
                connection.execute(
                    "UPDATE messages SET created_at = ? WHERE id = ?",
                    (f"2026-07-14 12:00:{index:02d}", message_id),
                )

        response = await client.post(
            "/api/chat",
            json={"message": "続きの質問", "thread_id": thread_id},
            headers=headers,
        )

    assert response.status_code == 200
    assert recording_agent.history is not None
    assert [message["content"] for message in recording_agent.history] == [
        f"message-{index}" for index in range(2, 10)
    ]


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
