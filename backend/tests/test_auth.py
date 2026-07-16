from __future__ import annotations

import httpx
import pytest


async def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_register_login_and_me(app) -> None:
    async with await _client(app) as client:
        register = await client.post(
            "/api/auth/register",
            json={"name": "来場者A"},
        )
        assert register.status_code == 201
        payload = register.json()
        assert payload["token"]
        assert payload["user"] == {
            "id": payload["user"]["id"],
            "name": "来場者A",
        }

        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {payload['token']}"})
        assert me.status_code == 200
        assert me.json()["user"]["name"] == "来場者A"

        login = await client.post("/api/auth/login", json={"name": "来場者A"})
        assert login.status_code == 200
        assert login.json()["token"] != payload["token"]


@pytest.mark.asyncio
async def test_register_duplicate_and_login_missing(app) -> None:
    async with await _client(app) as client:
        response = await client.post(
            "/api/auth/register",
            json={"name": "来場者B"},
        )
        assert response.status_code == 201

        duplicate = await client.post(
            "/api/auth/register",
            json={"name": "来場者B"},
        )
        assert duplicate.status_code == 409
        assert "すでに登録" in duplicate.json()["detail"]

        missing = await client.post("/api/auth/login", json={"name": "未登録"})
        assert missing.status_code == 404
        assert "まだ登録" in missing.json()["detail"]


@pytest.mark.asyncio
async def test_protected_routes_require_bearer(app) -> None:
    async with await _client(app) as client:
        response = await client.get("/api/auth/me")
        assert response.status_code == 401

        invalid = await client.get("/api/auth/me", headers={"Authorization": "Bearer invalid"})
        assert invalid.status_code == 401
