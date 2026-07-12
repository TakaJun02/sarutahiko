from __future__ import annotations

import sqlite3
from pathlib import Path


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    sources_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE
                );
                """
            )
        self._drop_legacy_users_role_column()

    def _drop_legacy_users_role_column(self) -> None:
        # FR-6 (2026-07-13): the visitor attribute was removed. Legacy databases
        # created before the change still carry users.role, so rebuild the users
        # table without it while keeping sessions/threads/messages intact.
        connection = sqlite3.connect(self.path)
        try:
            connection.row_factory = sqlite3.Row
            columns = connection.execute("PRAGMA table_info(users)").fetchall()
            if not any(column["name"] == "role" for column in columns):
                return
            # Foreign keys must be disabled outside the transaction so that
            # dropping the referenced users table does not violate constraints
            # declared by sessions/threads.
            connection.execute("PRAGMA foreign_keys = OFF")
            try:
                with connection:
                    connection.execute(
                        """
                        CREATE TABLE users_new (
                            id TEXT PRIMARY KEY,
                            name TEXT NOT NULL UNIQUE,
                            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    connection.execute(
                        "INSERT INTO users_new (id, name, created_at) "
                        "SELECT id, name, created_at FROM users"
                    )
                    connection.execute("DROP TABLE users")
                    connection.execute("ALTER TABLE users_new RENAME TO users")
            finally:
                connection.execute("PRAGMA foreign_keys = ON")
        finally:
            connection.close()
