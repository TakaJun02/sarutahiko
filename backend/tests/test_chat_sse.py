from __future__ import annotations

import json

import httpx
import pytest

from app.models.auth import User


class RecordingAgent:
    def __init__(self) -> None:
        self.history: list[dict] | None = None
        self.question: str | None = None

    async def stream(self, question, user, thread_id, message_id, history=None):
        self.question = question
        self.history = history
        yield "token", {"text": "記録済み"}
        yield "done", {"thread_id": thread_id, "message_id": message_id, "sources": []}

    @staticmethod
    def format_sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


class MapRecordingAgent(RecordingAgent):
    async def stream(self, question, user, thread_id, message_id, history=None):
        self.history = history
        yield "token", {"text": "経路です"}
        yield "map", {
            "mode": "route",
            "origin": {"node": "cafeteria", "label": "カフェテリア（食堂）"},
            "destination": {"node": "d", "label": "大学院棟", "room": "D414", "floor": 4},
            "path": {"nodes": ["cafeteria", "g1", "d"], "edges": ["E6a", "E1"]},
            "steps": ["カフェテリア（食堂）を出る", "4階の連絡通路で 大学院棟へ"],
        }
        yield "done", {"thread_id": thread_id, "message_id": message_id, "sources": []}


class ClarificationAgent(RecordingAgent):
    def __init__(self) -> None:
        super().__init__()
        self._metadata: dict[str, dict] = {}

    async def stream(self, question, user, thread_id, message_id, history=None):
        self.history = history
        self._metadata[message_id] = {"kind": "clarification"}
        yield "status", {"step": "evaluate", "text": "確認しています…"}
        yield "token", {"text": "どちらの学科について知りたいですか？"}
        yield "done", {"thread_id": thread_id, "message_id": message_id, "sources": []}

    def consume_message_metadata(self, message_id: str):
        return self._metadata.pop(message_id, None)


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
async def test_chat_sanitizes_ask_origin_assistant_content_only_for_agent_history(app) -> None:
    recording_agent = RecordingAgent()
    app.state.agent = recording_agent
    original_content = (
        "いまいる場所をマップでタップして教えてください！"
        "そこからの行き方をご案内します🗺️"
    )

    async with await _client(app) as client:
        register = await client.post("/api/auth/register", json={"name": "履歴サニタイズ"})
        auth = register.json()
        headers = {"Authorization": f"Bearer {auth['token']}"}
        user = User(**auth["user"])
        thread_id = app.state.thread_service.ensure_thread(user, None, "体育館に行きたい")
        app.state.thread_service.add_message(thread_id, "user", "体育館に行きたい")
        ask_message_id = app.state.thread_service.add_message(
            thread_id,
            "assistant",
            original_content,
            map_payload={
                "mode": "ask_origin",
                "origin": None,
                "destination": {"node": "gym", "label": "体育館"},
                "prompt": "いまいる場所をマップでタップしてください",
                "question": "体育館に行きたい",
            },
        )

        response = await client.post(
            "/api/chat",
            json={"message": "GI512はどこ？", "thread_id": thread_id},
            headers=headers,
        )
        history_response = await client.get(f"/api/threads/{thread_id}", headers=headers)

    assert response.status_code == 200
    assert recording_agent.history is not None
    agent_ask_message = next(
        message
        for message in recording_agent.history
        if (message.get("map") or {}).get("mode") == "ask_origin"
    )
    assert agent_ask_message["content"] == "（現在地の選択をお願いしました）"

    persisted_ask_message = next(
        message
        for message in history_response.json()["messages"]
        if message["id"] == ask_message_id
    )
    assert persisted_ask_message["content"] == original_content
    assert persisted_ask_message["map"]["mode"] == "ask_origin"


@pytest.mark.asyncio
async def test_chat_persists_and_sanitizes_clarification_metadata(app) -> None:
    clarification_agent = ClarificationAgent()
    app.state.agent = clarification_agent
    question = "どちらの学科について知りたいですか？"

    async with await _client(app) as client:
        auth_headers = await _auth_headers(client)
        first = await client.post(
            "/api/chat",
            json={"message": "研究について教えて", "thread_id": None},
            headers=auth_headers,
        )
        thread_id = _events(first.text)[-1][1]["thread_id"]
        history_response = await client.get(f"/api/threads/{thread_id}", headers=auth_headers)

        recording_agent = RecordingAgent()
        app.state.agent = recording_agent
        second = await client.post(
            "/api/chat",
            json={"message": "知能メカトロニクス学科です", "thread_id": thread_id},
            headers=auth_headers,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    persisted = history_response.json()["messages"][-1]
    assert persisted["content"] == question
    assert persisted["metadata"] == {"kind": "clarification"}
    assert recording_agent.history is not None
    clarification = next(
        message
        for message in recording_agent.history
        if (message.get("metadata") or {}).get("kind") == "clarification"
    )
    assert clarification["content"] == f"（確認質問）{question}"


@pytest.mark.asyncio
async def test_map_event_is_persisted_as_assistant_metadata_and_returned_by_thread_api(app) -> None:
    app.state.agent = MapRecordingAgent()

    async with await _client(app) as client:
        register = await client.post("/api/auth/register", json={"name": "マップ履歴"})
        headers = {"Authorization": f"Bearer {register.json()['token']}"}
        chat_response = await client.post(
            "/api/chat",
            json={"message": "食堂から D414 へ", "thread_id": None},
            headers=headers,
        )
        events = _events(chat_response.text)
        thread_id = events[-1][1]["thread_id"]
        history_response = await client.get(f"/api/threads/{thread_id}", headers=headers)

    assert [event for event, _ in events] == ["token", "map", "done"]
    messages = history_response.json()["messages"]
    assert messages[0]["map"] is None
    assert messages[1]["map"]["mode"] == "route"
    assert messages[1]["map"]["path"]["edges"] == ["E6a", "E1"]


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


@pytest.mark.asyncio
async def test_origin_node_is_synthesized_and_persisted_as_user_map_metadata(app) -> None:
    recording_agent = RecordingAgent()
    app.state.agent = recording_agent

    async with await _client(app) as client:
        auth_headers = await _auth_headers(client)
        response = await client.post(
            "/api/chat",
            json={
                "message": "D414 に行きたい",
                "thread_id": None,
                "origin_node": "cafeteria",
            },
            headers=auth_headers,
        )
        events = _events(response.text)
        thread_id = events[-1][1]["thread_id"]
        history_response = await client.get(f"/api/threads/{thread_id}", headers=auth_headers)

    synthesized = "現在地はカフェテリア（食堂）です。D414 に行きたい"
    assert response.status_code == 200
    assert recording_agent.question == synthesized
    user_message = history_response.json()["messages"][0]
    assert user_message["content"] == synthesized
    assert user_message["map"] == {
        "mode": "origin_select",
        "origin": {"node": "cafeteria", "label": "カフェテリア（食堂）"},
    }


@pytest.mark.asyncio
async def test_origin_select_content_is_available_to_following_turn_history(app) -> None:
    recording_agent = RecordingAgent()
    app.state.agent = recording_agent

    async with await _client(app) as client:
        auth_headers = await _auth_headers(client)
        selected = await client.post(
            "/api/chat",
            json={"message": "D414 に行きたい", "origin_node": "k"},
            headers=auth_headers,
        )
        thread_id = _events(selected.text)[-1][1]["thread_id"]
        following = await client.post(
            "/api/chat",
            json={"message": "じゃあ体育館は？", "thread_id": thread_id},
            headers=auth_headers,
        )

    assert following.status_code == 200
    assert recording_agent.history is not None
    assert "現在地は共通施設棟（総合受付）です。D414 に行きたい" in [
        message["content"] for message in recording_agent.history
    ]


@pytest.mark.asyncio
async def test_chat_rejects_unknown_origin_node_before_creating_a_thread(app) -> None:
    recording_agent = RecordingAgent()
    app.state.agent = recording_agent

    async with await _client(app) as client:
        auth_headers = await _auth_headers(client)
        response = await client.post(
            "/api/chat",
            json={"message": "D414 に行きたい", "origin_node": "unknown"},
            headers=auth_headers,
        )

    assert response.status_code == 422
    assert recording_agent.question is None
    with app.state.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM threads").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_omitting_origin_node_keeps_the_existing_sse_bytes(app) -> None:
    recording_agent = RecordingAgent()
    app.state.agent = recording_agent

    async with await _client(app) as client:
        auth_headers = await _auth_headers(client)
        response = await client.post(
            "/api/chat",
            json={"message": "通常の質問", "thread_id": None},
            headers=auth_headers,
        )

    events = _events(response.text)
    done = events[-1][1]
    expected = (
        "event: token\ndata: {\"text\":\"記録済み\"}\n\n"
        "event: done\ndata: "
        f"{{\"thread_id\":\"{done['thread_id']}\",\"message_id\":\"{done['message_id']}\","
        "\"sources\":[]}\n\n"
    )
    assert response.text == expected
    assert recording_agent.question == "通常の質問"
    with app.state.database.connect() as connection:
        row = connection.execute(
            "SELECT content, map_json FROM messages WHERE role = 'user'"
        ).fetchone()
    assert tuple(row) == ("通常の質問", None)
