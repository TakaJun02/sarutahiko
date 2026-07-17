from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.database import Database

LEGACY_SCHEMA = """
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK(role IN ('highschool', 'parent', 'other')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE threads (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    sources_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
);
"""


def _create_legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(LEGACY_SCHEMA)
        connection.execute(
            "INSERT INTO users (id, name, role, created_at) VALUES (?, ?, ?, ?)",
            ("user-1", "来場者A", "highschool", "2026-07-01 09:00:00"),
        )
        connection.execute(
            "INSERT INTO users (id, name, role, created_at) VALUES (?, ?, ?, ?)",
            ("user-2", "来場者B", "parent", "2026-07-02 10:00:00"),
        )
        connection.execute(
            "INSERT INTO sessions (token, user_id) VALUES (?, ?)",
            ("token-1", "user-1"),
        )
        connection.execute(
            "INSERT INTO threads (id, user_id, title) VALUES (?, ?, ?)",
            ("thread-1", "user-1", "食堂について"),
        )
        connection.execute(
            "INSERT INTO messages (id, thread_id, role, content) VALUES (?, ?, ?, ?)",
            ("message-1", "thread-1", "user", "食堂はどこですか？"),
        )
        connection.commit()
    finally:
        connection.close()


def _user_columns(connection: sqlite3.Connection) -> list[str]:
    return [row["name"] for row in connection.execute("PRAGMA table_info(users)")]


def test_initialize_drops_legacy_role_column_and_keeps_data(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    _create_legacy_database(db_path)

    database = Database(db_path)

    with database.connect() as connection:
        assert _user_columns(connection) == ["id", "name", "created_at"]

        users = connection.execute(
            "SELECT id, name, created_at FROM users ORDER BY id"
        ).fetchall()
        assert [(row["id"], row["name"], row["created_at"]) for row in users] == [
            ("user-1", "来場者A", "2026-07-01 09:00:00"),
            ("user-2", "来場者B", "2026-07-02 10:00:00"),
        ]

        sessions = connection.execute("SELECT token, user_id FROM sessions").fetchall()
        assert [(row["token"], row["user_id"]) for row in sessions] == [("token-1", "user-1")]

        threads = connection.execute("SELECT id, user_id, title FROM threads").fetchall()
        assert [(row["id"], row["user_id"], row["title"]) for row in threads] == [
            ("thread-1", "user-1", "食堂について")
        ]

        messages = connection.execute("SELECT id, thread_id, content FROM messages").fetchall()
        assert [(row["id"], row["thread_id"], row["content"]) for row in messages] == [
            ("message-1", "thread-1", "食堂はどこですか？")
        ]

        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_initialize_cascade_still_works_after_migration(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-cascade.sqlite3"
    _create_legacy_database(db_path)

    database = Database(db_path)

    with database.connect() as connection:
        connection.execute("DELETE FROM users WHERE id = ?", ("user-1",))
        assert connection.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"] == 0
        assert connection.execute("SELECT COUNT(*) AS c FROM threads").fetchone()["c"] == 0
        assert connection.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"] == 0


def test_initialize_is_idempotent_on_migrated_database(tmp_path: Path) -> None:
    db_path = tmp_path / "migrated.sqlite3"
    _create_legacy_database(db_path)

    Database(db_path)
    database = Database(db_path)

    with database.connect() as connection:
        assert _user_columns(connection) == ["id", "name", "created_at"]
        assert connection.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 2


def test_initialize_creates_fresh_database_without_role(tmp_path: Path) -> None:
    database = Database(tmp_path / "fresh.sqlite3")

    with database.connect() as connection:
        assert _user_columns(connection) == ["id", "name", "created_at"]
        message_columns = [row["name"] for row in connection.execute("PRAGMA table_info(messages)")]
        assert "map_json" in message_columns


def test_initialize_adds_map_metadata_column_to_existing_messages_table(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-map.sqlite3"
    _create_legacy_database(db_path)

    database = Database(db_path)

    with database.connect() as connection:
        message_columns = [row["name"] for row in connection.execute("PRAGMA table_info(messages)")]
        assert "map_json" in message_columns
        message = connection.execute(
            "SELECT id, content, map_json FROM messages WHERE id = ?",
            ("message-1",),
        ).fetchone()
        assert dict(message) == {
            "id": "message-1",
            "content": "食堂はどこですか？",
            "map_json": None,
        }
