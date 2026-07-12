from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from app.models.auth import User
from app.models.chat import DonePayload, Source, StatusPayload, TokenPayload


class MockCampusAgent:
    """Phase 1 mock agent. Replace this behind the same interface in Phase 3."""

    def __init__(self, status_delay_seconds: float = 1.0, token_delay_seconds: float = 0.035) -> None:
        self.status_delay_seconds = status_delay_seconds
        self.token_delay_seconds = token_delay_seconds

    async def stream(
        self,
        question: str,
        user: User,
        thread_id: str,
        message_id: str,
        history: list[dict] | None = None,
    ) -> AsyncIterator[tuple[str, dict]]:
        statuses = [
            StatusPayload(step="analyze", text="質問の意図を整理しています…"),
            StatusPayload(step="retrieve", text="学内ナレッジを検索しています…"),
            StatusPayload(step="search", text="学内資料を全文検索しています…"),
            StatusPayload(step="generate", text="回答をまとめています…"),
        ]

        for status in statuses:
            yield "status", status.model_dump()
            if self.status_delay_seconds > 0:
                await asyncio.sleep(self.status_delay_seconds)

        answer = self._answer(question=question, user=user)
        for token in self._chunk_answer(answer):
            yield "token", TokenPayload(text=token).model_dump()
            if self.token_delay_seconds > 0:
                await asyncio.sleep(self.token_delay_seconds)

        sources = [
            Source(
                title="秋田県立大学 公式サイト",
                url="https://www.akita-pu.ac.jp/",
                type="web",
            )
        ]
        yield "done", DonePayload(thread_id=thread_id, message_id=message_id, sources=sources).model_dump()

    @staticmethod
    def format_sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"

    @staticmethod
    def _answer(question: str, user: User) -> str:
        return (
            "ご質問ありがとうございます。\n\n"
            f"**「{question.strip()}」** について、Phase 1 ではモック回答を返しています。"
            "\n\n"
            "- 本荘キャンパスの学部・施設・アクセス案内を想定した回答形式です。\n"
            "- 実際の RAG と Web Search は Phase 3 で同じ SSE インターフェースに接続します。\n"
            "- 正式運用では、回答末尾に大学公式サイトなどの出典を表示します。\n\n"
            "現時点では、画面遷移・ログイン・ステータス表示・Markdown ストリーミングの確認用として利用してください。"
        )

    @staticmethod
    def _chunk_answer(answer: str) -> list[str]:
        chunks: list[str] = []
        buffer = ""
        for char in answer:
            buffer += char
            if char in "。\n、" or len(buffer) >= 12:
                chunks.append(buffer)
                buffer = ""
        if buffer:
            chunks.append(buffer)
        return chunks
