from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.mock import MockCampusAgent
from app.api import auth, chat
from app.core.config import Settings, load_settings
from app.core.database import Database
from app.services.auth import AuthService
from app.services.threads import ThreadService


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or load_settings()
    database = Database(app_settings.database_path)

    app = FastAPI(title="campus-guide-agent", version="0.1.0")
    app.state.settings = app_settings
    app.state.database = database
    app.state.auth_service = AuthService(database)
    app.state.thread_service = ThreadService(database)
    app.state.agent = MockCampusAgent(
        status_delay_seconds=app_settings.mock_status_delay_seconds,
        token_delay_seconds=app_settings.mock_token_delay_seconds,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.allow_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(chat.router)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "mock_agent": True}

    return app


app = create_app()
