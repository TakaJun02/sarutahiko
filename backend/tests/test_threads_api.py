from __future__ import annotations

import json

import httpx
import pytest


async def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def _auth_headers(client: httpx.AsyncClient, name: str = "テストユーザー") -> dict[str, str]:
    response = await client.post(
        "/api/auth/register",
        json={"name": name, "role": "highschool"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['token']}"}


async def _create_thread(client: httpx.AsyncClient, headers: dict[str, str], message: str) -> str:
    response = await client.post(
        "/api/chat",
        json={"message": message, "thread_id": None},
        headers=headers,
    )
    assert response.status_code == 200
    for block in response.text.strip().split("\n\n"):
        lines = block.splitlines()
        if lines[0] == "event: done":
            return json.loads(lines[1].removeprefix("data: "))["thread_id"]
    raise AssertionError("done event not found in SSE stream")


def _set_updated_at(app, thread_id: str, updated_at: str) -> None:
    with app.state.database.connect() as connection:
        connection.execute(
            "UPDATE threads SET updated_at = ? WHERE id = ?",
            (updated_at, thread_id),
        )


@pytest.mark.asyncio
async def test_list_threads_orders_by_updated_at_desc(app) -> None:
    async with await _client(app) as client:
        headers = await _auth_headers(client)
        older = await _create_thread(client, headers, "食堂はどこですか？")
        newer = await _create_thread(client, headers, "図書館は使えますか？")
        _set_updated_at(app, older, "2026-07-13 09:00:00")
        _set_updated_at(app, newer, "2026-07-13 10:00:00")

        response = await client.get("/api/threads", headers=headers)
        assert response.status_code == 200
        threads = response.json()["threads"]
        assert [thread["id"] for thread in threads] == [newer, older]
        assert set(threads[0]) == {"id", "title", "created_at", "updated_at"}
        assert threads[1]["title"] == "食堂はどこですか？"


@pytest.mark.asyncio
async def test_list_threads_only_returns_own_threads(app) -> None:
    async with await _client(app) as client:
        headers_a = await _auth_headers(client, "来場者A")
        headers_b = await _auth_headers(client, "来場者B")
        thread_a = await _create_thread(client, headers_a, "アクセス方法は？")

        response = await client.get("/api/threads", headers=headers_b)
        assert response.status_code == 200
        assert response.json()["threads"] == []

        response = await client.get("/api/threads", headers=headers_a)
        assert [thread["id"] for thread in response.json()["threads"]] == [thread_a]


@pytest.mark.asyncio
async def test_rename_thread_strips_and_updates_title(app) -> None:
    async with await _client(app) as client:
        headers = await _auth_headers(client)
        thread_id = await _create_thread(client, headers, "寮はありますか？")

        response = await client.patch(
            f"/api/threads/{thread_id}",
            json={"title": "  学生寮について  "},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["thread"]["title"] == "学生寮について"

        listed = await client.get("/api/threads", headers=headers)
        assert listed.json()["threads"][0]["title"] == "学生寮について"


@pytest.mark.asyncio
async def test_rename_thread_validates_title_length(app) -> None:
    async with await _client(app) as client:
        headers = await _auth_headers(client)
        thread_id = await _create_thread(client, headers, "サークルは？")

        blank = await client.patch(
            f"/api/threads/{thread_id}",
            json={"title": "   "},
            headers=headers,
        )
        assert blank.status_code == 422

        too_long = await client.patch(
            f"/api/threads/{thread_id}",
            json={"title": "あ" * 61},
            headers=headers,
        )
        assert too_long.status_code == 422

        max_length = await client.patch(
            f"/api/threads/{thread_id}",
            json={"title": "あ" * 60},
            headers=headers,
        )
        assert max_length.status_code == 200
        assert max_length.json()["thread"]["title"] == "あ" * 60


@pytest.mark.asyncio
async def test_delete_thread_removes_thread_and_messages(app) -> None:
    async with await _client(app) as client:
        headers = await _auth_headers(client)
        thread_id = await _create_thread(client, headers, "駐車場はありますか？")

        response = await client.delete(f"/api/threads/{thread_id}", headers=headers)
        assert response.status_code == 204
        assert response.content == b""

        missing = await client.get(f"/api/threads/{thread_id}", headers=headers)
        assert missing.status_code == 404

    with app.state.database.connect() as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()[0]
    assert remaining == 0


@pytest.mark.asyncio
async def test_thread_mutations_reject_other_users(app) -> None:
    async with await _client(app) as client:
        headers_a = await _auth_headers(client, "来場者A")
        headers_b = await _auth_headers(client, "来場者B")
        thread_id = await _create_thread(client, headers_a, "学食のおすすめは？")

        rename = await client.patch(
            f"/api/threads/{thread_id}",
            json={"title": "乗っ取りタイトル"},
            headers=headers_b,
        )
        assert rename.status_code == 404

        delete = await client.delete(f"/api/threads/{thread_id}", headers=headers_b)
        assert delete.status_code == 404

        fetch = await client.get(f"/api/threads/{thread_id}", headers=headers_b)
        assert fetch.status_code == 404

        still_there = await client.get(f"/api/threads/{thread_id}", headers=headers_a)
        assert still_there.status_code == 200


@pytest.mark.asyncio
async def test_thread_endpoints_require_auth(app) -> None:
    async with await _client(app) as client:
        assert (await client.get("/api/threads")).status_code == 401
        assert (
            await client.patch("/api/threads/some-id", json={"title": "x"})
        ).status_code == 401
        assert (await client.delete("/api/threads/some-id")).status_code == 401
