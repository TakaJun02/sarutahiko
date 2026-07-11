from __future__ import annotations

from app.agent.graph import RealCampusAgent
from app.models.auth import User
from app.rag.models import KnowledgeChunk
from app.search.models import WebSearchResult

import pytest

pytestmark = pytest.mark.asyncio


class FakeLLMClient:
    def __init__(self, tokens: list[str] | None = None) -> None:
        self.tokens = tokens or ["回答", "です。"]
        self.calls: list[dict] = []

    async def stream_chat(self, messages, *, enable_thinking: bool):
        self.calls.append({"messages": messages, "enable_thinking": enable_thinking})
        for token in self.tokens:
            yield token


class FakeKnowledgeStore:
    def __init__(self, results: list[KnowledgeChunk]) -> None:
        self.results = results
        self.calls: list[dict] = []

    async def search(self, query: str, *, limit: int):
        self.calls.append({"query": query, "limit": limit})
        return self.results


class FakeSearchProvider:
    def __init__(self, results: list[WebSearchResult]) -> None:
        self.results = results
        self.calls: list[dict] = []

    async def search(self, query: str, *, max_results: int):
        self.calls.append({"query": query, "max_results": max_results})
        return self.results


def _user(role: str = "highschool") -> User:
    return User(id="user-1", name="テスト", role=role)


async def _collect(agent: RealCampusAgent, question: str, history: list[dict] | None = None):
    return [
        event
        async for event in agent.stream(
            question,
            _user(),
            "thread-1",
            "message-1",
            history=history,
        )
    ]


def _chunk(**overrides) -> KnowledgeChunk:
    values = {
        "id": "chunk-1",
        "text": "本荘キャンパスには食堂がある施設が案内されています。",
        "category": "facility",
        "confidence": "high",
        "title": "食堂",
        "source_urls": ["https://example.test/facility"],
        "score": 0.92,
    }
    values.update(overrides)
    return KnowledgeChunk(**values)


async def test_real_agent_emits_status_events_in_order_and_stops() -> None:
    llm = FakeLLMClient()
    store = FakeKnowledgeStore([_chunk()])
    search = FakeSearchProvider([])
    agent = RealCampusAgent(llm_client=llm, knowledge_store=store, search_provider=search)

    events = await _collect(agent, "食堂はどこですか？", history=[{"role": "user", "content": "前の質問"}])

    status_steps = [payload["step"] for event, payload in events if event == "status"]
    assert status_steps == ["analyze", "retrieve", "evaluate", "generate"]
    assert [event for event, _ in events[-3:]] == ["token", "token", "done"]
    assert events[-1][1]["sources"] == [
        {"title": "食堂", "url": "https://example.test/facility", "type": "knowledge"}
    ]
    assert llm.calls[0]["enable_thinking"] is False
    assert store.calls[0]["limit"] == 6
    assert search.calls == []
    assert any(message["content"] == "前の質問" for message in llm.calls[0]["messages"])


async def test_real_agent_branches_to_web_search_when_knowledge_is_insufficient() -> None:
    llm = FakeLLMClient(tokens=["最新情報です。"])
    store = FakeKnowledgeStore([])
    search_result = WebSearchResult(
        title="公式オープンキャンパス",
        url="https://example.test/open-campus",
        snippet="2026年の開催情報です。",
    )
    search = FakeSearchProvider([search_result])
    agent = RealCampusAgent(llm_client=llm, knowledge_store=store, search_provider=search)

    events = await _collect(agent, "最新のオープンキャンパス日程は？")

    status_steps = [payload["step"] for event, payload in events if event == "status"]
    assert status_steps == ["analyze", "retrieve", "evaluate", "web_search", "generate"]
    assert search.calls[0]["max_results"] == 3
    assert events[-1] == (
        "done",
        {
            "thread_id": "thread-1",
            "message_id": "message-1",
            "sources": [
                {"title": "公式オープンキャンパス", "url": "https://example.test/open-campus", "type": "web"}
            ],
        },
    )


async def test_real_agent_deduplicates_sources_from_generation_context() -> None:
    llm = FakeLLMClient(tokens=["回答"])
    store = FakeKnowledgeStore(
        [
            _chunk(id="chunk-1", title="施設A", source_urls=["https://example.test/shared"]),
            _chunk(id="chunk-2", title="施設B", source_urls=["https://example.test/shared"]),
        ]
    )
    search = FakeSearchProvider([])
    agent = RealCampusAgent(llm_client=llm, knowledge_store=store, search_provider=search)

    events = await _collect(agent, "施設について教えて")

    assert events[-1][1]["sources"] == [
        {"title": "施設A", "url": "https://example.test/shared", "type": "knowledge"}
    ]
