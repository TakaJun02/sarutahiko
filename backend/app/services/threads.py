from __future__ import annotations

import json
import sqlite3
import uuid

from fastapi import HTTPException, status

from app.core.database import Database
from app.models.auth import User
from app.models.chat import Source


class ThreadService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def ensure_thread(self, user: User, thread_id: str | None, first_message: str) -> str:
        if thread_id:
            with self.database.connect() as connection:
                row = connection.execute(
                    "SELECT id FROM threads WHERE id = ? AND user_id = ?",
                    (thread_id, user.id),
                ).fetchone()
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="スレッドが見つかりません。",
                )
            return thread_id

        title = first_message.strip().replace("\n", " ")[:40] or "新しい会話"
        new_thread_id = str(uuid.uuid4())
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO threads (id, user_id, title) VALUES (?, ?, ?)",
                (new_thread_id, user.id, title),
            )
        return new_thread_id

    def add_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        sources: list[Source | dict] | None = None,
        map_payload: dict | None = None,
        message_id: str | None = None,
    ) -> str:
        new_message_id = message_id or str(uuid.uuid4())
        sources_json = None
        if sources is not None:
            serialized_sources = [
                source.model_dump() if isinstance(source, Source) else source
                for source in sources
            ]
            sources_json = json.dumps(serialized_sources, ensure_ascii=False)
        map_json = json.dumps(map_payload, ensure_ascii=False) if map_payload is not None else None
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO messages (id, thread_id, role, content, sources_json, map_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (new_message_id, thread_id, role, content, sources_json, map_json),
            )
            connection.execute(
                "UPDATE threads SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (thread_id,),
            )
        return new_message_id

    def get_recent_messages(self, thread_id: str, limit: int = 6) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, role, content, sources_json, map_json, created_at
                FROM messages
                WHERE thread_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (thread_id, limit),
            ).fetchall()
        return [self._message_to_dict(row) for row in reversed(rows)]

    def list_threads(self, user: User) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM threads
                WHERE user_id = ?
                ORDER BY updated_at DESC, created_at DESC, rowid DESC
                """,
                (user.id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def rename_thread(self, user: User, thread_id: str, title: str) -> dict:
        normalized = title.strip()
        if not normalized or len(normalized) > 60:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="スレッド名は1〜60文字で入力してください。",
            )
        with self.database.connect() as connection:
            self._require_owned_thread(connection, user, thread_id)
            connection.execute(
                "UPDATE threads SET title = ? WHERE id = ?",
                (normalized, thread_id),
            )
            thread = connection.execute(
                "SELECT id, title, created_at, updated_at FROM threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
        return dict(thread)

    def delete_thread(self, user: User, thread_id: str) -> None:
        with self.database.connect() as connection:
            self._require_owned_thread(connection, user, thread_id)
            # messages are removed via ON DELETE CASCADE (PRAGMA foreign_keys = ON).
            connection.execute("DELETE FROM threads WHERE id = ?", (thread_id,))

    def get_thread(self, user: User, thread_id: str) -> dict:
        with self.database.connect() as connection:
            thread = connection.execute(
                "SELECT id, title, created_at, updated_at FROM threads WHERE id = ? AND user_id = ?",
                (thread_id, user.id),
            ).fetchone()
            if thread is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="スレッドが見つかりません。",
                )
            messages = connection.execute(
                """
                SELECT id, role, content, sources_json, map_json, created_at
                FROM messages
                WHERE thread_id = ?
                ORDER BY created_at ASC
                """,
                (thread_id,),
            ).fetchall()
        return {
            "thread": dict(thread),
            "messages": [self._message_to_dict(message) for message in messages],
        }

    @staticmethod
    def _require_owned_thread(connection: sqlite3.Connection, user: User, thread_id: str) -> None:
        row = connection.execute(
            "SELECT id FROM threads WHERE id = ? AND user_id = ?",
            (thread_id, user.id),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="スレッドが見つかりません。",
            )

    @staticmethod
    def _message_to_dict(row: sqlite3.Row) -> dict:
        sources = json.loads(row["sources_json"]) if row["sources_json"] else []
        map_payload = json.loads(row["map_json"]) if row["map_json"] else None
        return {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "sources": sources,
            "map": map_payload,
            "created_at": row["created_at"],
        }
