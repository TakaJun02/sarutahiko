from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AgentMode = Literal["mock", "real"]
DEFAULT_LLM_MODEL = "google/gemma-4-31B-it-qat-w4a16-ct"
DEFAULT_LLM_CONTEXT_WINDOW = 2816
DEFAULT_LLM_ANSWER_MAX_TOKENS = 640


@dataclass(frozen=True)
class Settings:
    database_path: Path
    agent_mode: AgentMode = "real"
    mock_status_delay_seconds: float = 1.0
    mock_token_delay_seconds: float = 0.035
    vllm_base_url: str = "http://127.0.0.1:8000/v1"
    llm_model: str = DEFAULT_LLM_MODEL
    llm_context_window: int = DEFAULT_LLM_CONTEXT_WINDOW
    llm_answer_max_tokens: int = DEFAULT_LLM_ANSWER_MAX_TOKENS
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "campus_knowledge"
    embedding_model: str = "BAAI/bge-m3"
    retrieval_top_k: int = 6
    retrieval_min_score: float = 0.45
    allow_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )


def load_settings() -> Settings:
    default_database_path = Path(__file__).resolve().parents[2] / "data" / "campus-guide.sqlite3"
    database_path = Path(os.getenv("DATABASE_PATH", str(default_database_path)))
    agent_mode = _parse_agent_mode(os.getenv("AGENT_MODE", "real"))
    status_delay = float(os.getenv("MOCK_STATUS_DELAY_SECONDS", "1.0"))
    token_delay = float(os.getenv("MOCK_TOKEN_DELAY_SECONDS", "0.035"))
    allow_origins = tuple(
        origin.strip()
        for origin in os.getenv(
            "CORS_ALLOW_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    )
    return Settings(
        database_path=database_path,
        agent_mode=agent_mode,
        mock_status_delay_seconds=status_delay,
        mock_token_delay_seconds=token_delay,
        vllm_base_url=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1"),
        llm_model=os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL),
        llm_context_window=int(os.getenv("LLM_CONTEXT_WINDOW", str(DEFAULT_LLM_CONTEXT_WINDOW))),
        llm_answer_max_tokens=int(os.getenv("LLM_ANSWER_MAX_TOKENS", str(DEFAULT_LLM_ANSWER_MAX_TOKENS))),
        qdrant_url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
        qdrant_collection=os.getenv("QDRANT_COLLECTION", "campus_knowledge"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3"),
        retrieval_top_k=int(os.getenv("RAG_TOP_K", "6")),
        retrieval_min_score=float(os.getenv("RAG_MIN_SCORE", "0.45")),
        allow_origins=allow_origins,
    )


def _parse_agent_mode(value: str) -> AgentMode:
    normalized = value.strip().lower()
    if normalized not in {"mock", "real"}:
        raise ValueError("AGENT_MODE must be 'mock' or 'real'")
    return normalized  # type: ignore[return-value]
