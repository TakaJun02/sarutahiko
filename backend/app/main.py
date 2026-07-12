from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.graph import RealCampusAgent
from app.agent.mock import MockCampusAgent
from app.api import auth, chat
from app.core.config import Settings, load_settings
from app.core.database import Database
from app.llm.client import VLLMClient
from app.rag.embeddings import EmbeddingModel
from app.rag.lexical import CampusLexicalSearch
from app.rag.qdrant_store import CampusKnowledgeStore
from app.search.tavily import TavilySearchProvider
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
    _configure_agent(app, app_settings)

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
        vllm = await _safe_health(getattr(app.state, "vllm_health", None))
        qdrant = await _safe_health(getattr(app.state, "qdrant_health", None))
        degraded = any(check["ok"] is False for check in (vllm, qdrant))
        return {
            "status": "degraded" if degraded else "ok",
            "agent_mode": app_settings.agent_mode,
            "vllm": vllm,
            "qdrant": qdrant,
        }

    return app


def _configure_agent(app: FastAPI, settings: Settings) -> None:
    if settings.agent_mode == "mock":
        app.state.agent = MockCampusAgent(
            status_delay_seconds=settings.mock_status_delay_seconds,
            token_delay_seconds=settings.mock_token_delay_seconds,
        )
        app.state.vllm_health = None
        app.state.qdrant_health = None
        return

    llm_client = VLLMClient(base_url=settings.vllm_base_url, model=settings.llm_model)
    embedding_model = EmbeddingModel(
        model_name=settings.embedding_model,
        device="cpu",
        base_url=settings.embedding_base_url,
    )
    knowledge_store = CampusKnowledgeStore(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
        embedding_model=embedding_model,
    )
    search_provider = TavilySearchProvider(api_key=settings.tavily_api_key)
    lexical_search = CampusLexicalSearch(settings.knowledge_dir)

    app.state.agent = RealCampusAgent(
        llm_client=llm_client,
        knowledge_store=knowledge_store,
        lexical_search=lexical_search,
        search_provider=search_provider,
        top_k=settings.retrieval_top_k,
        min_relevance_score=settings.retrieval_min_score,
        llm_context_window=settings.llm_context_window,
        llm_answer_max_tokens=settings.llm_answer_max_tokens,
    )
    app.state.vllm_health = llm_client.health
    app.state.qdrant_health = knowledge_store.health


async def _safe_health(check: Callable[[], Awaitable[dict]] | None) -> dict:
    if check is None:
        return {"ok": None, "status": "skipped"}
    try:
        return await check()
    except Exception as exc:
        return {"ok": False, "status": "error", "message": str(exc)}


app = create_app()
