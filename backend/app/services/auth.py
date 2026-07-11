from __future__ import annotations

import secrets
import sqlite3
import uuid

from fastapi import HTTPException, status

from app.core.database import Database
from app.models.auth import Role, User


class AuthService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def register(self, name: str, role: Role) -> tuple[str, User]:
        user_id = str(uuid.uuid4())
        token = self._new_token()
        try:
            with self.database.connect() as connection:
                connection.execute(
                    "INSERT INTO users (id, name, role) VALUES (?, ?, ?)",
                    (user_id, name, role),
                )
                connection.execute(
                    "INSERT INTO sessions (token, user_id) VALUES (?, ?)",
                    (token, user_id),
                )
        except sqlite3.IntegrityError as exc:
            if "users.name" in str(exc) or "UNIQUE constraint failed: users.name" in str(exc):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="このニックネームはすでに登録されています。",
                ) from exc
            raise
        return token, User(id=user_id, name=name, role=role)

    def login(self, name: str) -> tuple[str, User]:
        token = self._new_token()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, name, role FROM users WHERE name = ?",
                (name,),
            ).fetchone()
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="このニックネームはまだ登録されていません。",
                )
            connection.execute(
                "INSERT INTO sessions (token, user_id) VALUES (?, ?)",
                (token, row["id"]),
            )
        return token, self._row_to_user(row)

    def get_user_by_token(self, token: str) -> User | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT users.id, users.name, users.role
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = ?
                """,
                (token,),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def require_user(self, token: str) -> User:
        user = self.get_user_by_token(token)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="認証が必要です。",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user

    @staticmethod
    def _new_token() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        return User(id=row["id"], name=row["name"], role=row["role"])
