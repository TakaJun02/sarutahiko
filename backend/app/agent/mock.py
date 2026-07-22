from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from app.models.auth import User
from app.models.chat import DonePayload, Source, StatusPayload, TokenPayload
from app.services.time_context import build_time_context

CLARIFY_STATUS_TEXT = "案内に必要なことを少しだけ確認します。"


class MockCampusAgent:
    """Phase 1 mock agent. Replace this behind the same interface in Phase 3."""

    def __init__(self, status_delay_seconds: float = 1.0, token_delay_seconds: float = 0.035) -> None:
        self.status_delay_seconds = status_delay_seconds
        self.token_delay_seconds = token_delay_seconds
        self._message_metadata: dict[str, dict] = {}

    async def stream(
        self,
        question: str,
        user: User,
        thread_id: str,
        message_id: str,
        history: list[dict] | None = None,
    ) -> AsyncIterator[tuple[str, dict]]:
        if "確認テスト" in question:
            async for event in self._stream_clarification_test(thread_id, message_id):
                yield event
            return

        statuses = [
            StatusPayload(step="analyze", text="ご質問をじっくり読み解いています…"),
            StatusPayload(
                step="analyze",
                text="ご質問のポイントを整理しています…",
                partial=True,
            ),
            StatusPayload(
                step="analyze",
                text="ご質問のポイントを整理しています。必要な資料を見極めています…",
                partial=True,
            ),
            StatusPayload(
                step="analyze",
                text="ご質問のポイントを整理しています。必要な資料を見極めています。",
            ),
            StatusPayload(step="retrieve", text="キャンパスの資料を探しています…"),
            StatusPayload(step="search", text="学内資料をすみずみまで調べています…"),
            StatusPayload(step="generate", text="とっておきの回答をまとめています…"),
        ]

        for status in statuses:
            yield "status", status.model_dump()
            if self.status_delay_seconds > 0:
                await asyncio.sleep(self.status_delay_seconds)

        answer = self._answer(question=question)
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

    async def _stream_clarification_test(
        self,
        thread_id: str,
        message_id: str,
    ) -> AsyncIterator[tuple[str, dict]]:
        statuses = [
            StatusPayload(step="analyze", text="ご質問を確認しています…"),
            StatusPayload(step="clarify", text=CLARIFY_STATUS_TEXT),
        ]
        for status in statuses:
            yield "status", status.model_dump()
            if self.status_delay_seconds > 0:
                await asyncio.sleep(self.status_delay_seconds)

        question = "どの学科についてお調べしましょうか？ 気になっている学科名を教えてください。"
        for token in self._chunk_answer(question):
            yield "token", TokenPayload(text=token).model_dump()
            if self.token_delay_seconds > 0:
                await asyncio.sleep(self.token_delay_seconds)

        self._message_metadata[message_id] = {"kind": "clarification"}
        yield "done", DonePayload(
            thread_id=thread_id,
            message_id=message_id,
            sources=[],
            kind="clarification",
        ).model_dump()

    def consume_message_metadata(self, message_id: str) -> dict | None:
        return self._message_metadata.pop(message_id, None)

    @staticmethod
    def format_sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"

    @staticmethod
    def _answer(question: str) -> str:
        # The second line of the time context is the event-phase headline
        # (countdown / ongoing / finished), handy for manual verification.
        time_lines = build_time_context().splitlines()
        time_note = time_lines[1] if len(time_lines) > 1 else time_lines[0]
        return (
            "ご質問ありがとうございます！\n\n"
            f"**「{question.strip()}」** について、Phase 1 ではモック回答を返していますよ！\n\n"
            f"{time_note}\n\n"
            "- 本荘キャンパスの学部・施設・アクセス案内を想定した回答形式です。\n"
            "- 実際の RAG と Web Search は Phase 3 で同じ SSE インターフェースに接続します。\n"
            "- 正式運用では、回答末尾に大学公式サイトなどの出典を表示します。\n\n"
            "画面遷移・ログイン・ステータス表示・Markdown ストリーミングの確認用として、ぜひ試してみてくださいね！"
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
