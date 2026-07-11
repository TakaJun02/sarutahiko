from __future__ import annotations

import pytest

from app.core.config import Settings
from app.main import create_app


@pytest.fixture()
def app(tmp_path):
    settings = Settings(
        database_path=tmp_path / "test.sqlite3",
        mock_status_delay_seconds=0,
        mock_token_delay_seconds=0,
        allow_origins=("http://testserver",),
    )
    return create_app(settings)
