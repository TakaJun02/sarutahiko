from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_path: Path
    mock_status_delay_seconds: float = 1.0
    mock_token_delay_seconds: float = 0.035
    allow_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )


def load_settings() -> Settings:
    default_database_path = Path(__file__).resolve().parents[2] / "data" / "campus-guide.sqlite3"
    database_path = Path(os.getenv("DATABASE_PATH", str(default_database_path)))
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
        mock_status_delay_seconds=status_delay,
        mock_token_delay_seconds=token_delay,
        allow_origins=allow_origins,
    )
