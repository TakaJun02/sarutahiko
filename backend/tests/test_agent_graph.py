from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest
import httpx
from openai import BadRequestError

from app.agent.graph import (
    GENERATE_SYSTEM_PROMPT,
    MIN_GENERATION_CONTEXT_TOKENS,
    PROMPT_MARGIN_TOKENS,
    RealCampusAgent,
    estimate_tokens,
)
from app.models.auth import User
from app.rag.lexical import (
    CampusLexicalSearch,
    LexicalSearchOutcome,
    SectionHit,
    generate_keyword_variants,
)
from app.rag.models import KnowledgeChunk
from app.search.models import WebSearchResult
from knowledge.ingest.ingest import build_knowledge_chunks, chunk_markdown, parse_frontmatter

pytestmark = pytest.mark.asyncio


class FakeLLMClient:
    def __init__(
        self,
        *,
        completions: list[str] | None = None,
        tokens: list[str] | None = None,
        token_counts: list[int | None] | None = None,
    ) -> None:
        self.completions = list(completions or [])
        self.tokens = tokens or ["回答", "です。"]
        self.token_counts = list(token_counts or [])
        self.complete_calls: list[dict] = []
        self.stream_calls: list[dict] = []
        self.count_token_texts: list[str] = []

    async def complete_chat(
        self,
        messages,
        *,
        temperature: float,
        max_tokens: int,
        enable_thinking: bool,
    ) -> str:
        self.complete_calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "enable_thinking": enable_thinking,
            }
        )
        if self.completions:
            return self.completions.pop(0)
        return '{"sufficient": true, "missing": "", "web_queries": []}'

    async def count_tokens(self, text: str) -> int | None:
        self.count_token_texts.append(text)
        if self.token_counts:
            return self.token_counts.pop(0)
        return None

    async def stream_chat(
        self,
        messages,
        *,
        temperature: float,
        max_tokens: int,
        enable_thinking: bool,
    ):
        self.stream_calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "enable_thinking": enable_thinking,
            }
        )
        for token in self.tokens:
            yield token


class RetryLLMClient(FakeLLMClient):
    def __init__(self, *, completions: list[str] | None = None) -> None:
        super().__init__(completions=completions, tokens=["retry ok"])
        self._failed_once = False

    async def stream_chat(
        self,
        messages,
        *,
        temperature: float,
        max_tokens: int,
        enable_thinking: bool,
    ):
        self.stream_calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "enable_thinking": enable_thinking,
            }
        )
        if not self._failed_once:
            self._failed_once = True
            response = httpx.Response(
                400,
                request=httpx.Request("POST", "http://vllm.test/v1/chat/completions"),
            )
            raise BadRequestError(
                "maximum context length is 2816 tokens, prompt contains too many tokens",
                response=response,
                body={"message": "maximum context length is 2816 tokens"},
            )
        for token in self.tokens:
            yield token


class FakeKnowledgeStore:
    def __init__(self, results) -> None:
        self.results = results
        self.calls: list[dict] = []

    async def search(self, query: str, *, limit: int):
        self.calls.append({"query": query, "limit": limit})
        if isinstance(self.results, dict):
            return self.results.get(query, [])
        return self.results


class FakeSearchProvider:
    def __init__(self, results: list[WebSearchResult]) -> None:
        self.results = results
        self.calls: list[dict] = []

    async def search(self, query: str, *, max_results: int, include_domains=None):
        self.calls.append(
            {
                "query": query,
                "max_results": max_results,
                "include_domains": include_domains,
            }
        )
        offset = (len(self.calls) - 1) * max_results
        rows = self.results[offset : offset + max_results] or self.results[:max_results]
        return rows[:max_results]


class FakeLexicalSearch:
    def __init__(self, outcome: LexicalSearchOutcome | None = None) -> None:
        self.outcome = outcome or LexicalSearchOutcome([], [], [], False)
        self.calls: list[list[str]] = []

    def grep_sections_with_trace(self, keywords):
        self.calls.append(list(keywords))
        return self.outcome


def _user() -> User:
    return User(id="user-1", name="テスト")


_FIXED_TIME_CONTEXT = (
    "現在日時: 2026年7月13日（月）14:05\n"
    "オープンキャンパス2026（2026年7月19日（日）9:30〜15:00・本荘キャンパス）まであと6日です。"
)


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


def _agent(
    *,
    llm: FakeLLMClient | None = None,
    store: FakeKnowledgeStore | None = None,
    search: FakeSearchProvider | None = None,
    lexical: FakeLexicalSearch | CampusLexicalSearch | None = None,
    http_client_factory=None,
    llm_context_window: int = 2816,
    llm_answer_max_tokens: int = 640,
) -> RealCampusAgent:
    return RealCampusAgent(
        llm_client=llm or FakeLLMClient(),
        knowledge_store=store or FakeKnowledgeStore([]),
        search_provider=search or FakeSearchProvider([]),
        lexical_search=lexical,
        http_client_factory=http_client_factory,
        llm_context_window=llm_context_window,
        llm_answer_max_tokens=llm_answer_max_tokens,
        time_context_provider=lambda: _FIXED_TIME_CONTEXT,
    )


def _http_factory(html_by_url: dict[str, str]):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html_by_url[str(request.url)])

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=8.0)


def _message_tokens(messages: list[dict[str, str]]) -> int:
    return sum(estimate_tokens(message["content"]) for message in messages)


def _long_history(prefix: str = "HISTORY") -> list[dict[str, str]]:
    return [
        {"role": "user", "content": f"{prefix}_USER_1 " + ("あ" * 600)},
        {"role": "assistant", "content": f"{prefix}_ASSISTANT_1 " + ("い" * 600)},
        {"role": "user", "content": f"{prefix}_USER_2 " + ("う" * 600)},
        {"role": "assistant", "content": f"{prefix}_ASSISTANT_2 " + ("え" * 600)},
    ]


def _long_context_chunk() -> KnowledgeChunk:
    return _chunk(id="ctx", title="長い根拠", score=0.99, text="CTX_START " + ("根拠本文" * 1200) + " CTX_END")


def _write_chunked_knowledge_file(
    tmp_path: Path,
    *,
    file_id: str = "lab-cps-members",
    section_count: int = 8,
    matching_indices: set[int] | None = None,
) -> tuple[CampusLexicalSearch, list[KnowledgeChunk]]:
    matching_indices = matching_indices or set()
    sections = "\n\n".join(
        f"## セクション{index}\n"
        f"{'学生メンバー ' if index in matching_indices else ''}"
        f"{file_id} のチャンク {index} です。"
        for index in range(section_count)
    )
    (tmp_path / f"{file_id}.md").write_text(
        f"""---
id: {file_id}
category: lab
title: サイバーフィジカルシステム研究室 メンバー一覧
source_urls:
  - https://example.test/{file_id}
retrieved_at: 2026-07-12
confidence: high
---

{sections}
""",
        encoding="utf-8",
    )
    lexical = CampusLexicalSearch(tmp_path)
    chunks = [section.chunk for section in lexical._load_sections() if section.chunk.file_id == file_id]
    assert len(chunks) == section_count
    return lexical, chunks


async def test_estimate_tokens_uses_japanese_character_heuristic() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("あ") == 1
    assert estimate_tokens("あいうえ") == 3
    text = "秋田県立大学本荘キャンパス"
    assert estimate_tokens(text) == (len(text) * 3) // 4


async def test_keyword_variants_strip_suffix_and_extract_script_runs() -> None:
    cps_variants = generate_keyword_variants(["サイバーフィジカルシステム研究室"])
    variants = generate_keyword_variants(["サイバーフィジカルシステム研究室", "知能メカトロニクス学科"])

    assert cps_variants == ["サイバーフィジカルシステム"]
    assert "サイバーフィジカルシステム" in variants
    assert "研究室" not in variants
    assert "知能メカトロニクス" in variants
    assert "メカトロニクス" in variants
    assert "知能" in variants
    assert generate_keyword_variants(["研究室"]) == []


async def test_lexical_search_scores_distinct_keywords_then_hits_and_uses_ingest_ids(tmp_path: Path) -> None:
    path = tmp_path / "faculty-management.md"
    path.write_text(
        """---
id: faculty-management
category: faculty
title: 経営システム工学科
source_urls:
  - https://example.test/faculty
retrieved_at: 2026-07-11
confidence: high
---

## 教員一覧
山口高康教授はサイバーフィジカルシステム研究室を担当します。

## 研究室
サイバーフィジカルシステム研究室ではサイバーフィジカルを扱います。
""",
        encoding="utf-8",
    )
    lexical = CampusLexicalSearch(tmp_path)

    hits = lexical.grep_sections(["サイバーフィジカル", "山口高康"])
    ingest_document = parse_frontmatter(path)
    ingest_chunks = build_knowledge_chunks(ingest_document, chunk_markdown(ingest_document.body))

    assert [hit.distinct_keyword_hits for hit in hits[:2]] == [2, 1]
    assert hits[0].chunk.id == ingest_chunks[0].id
    assert hits[0].chunk.grep_hit is True
    assert hits[0].chunk.grep_keywords == ("サイバーフィジカル", "山口高康")


async def test_lexical_search_single_keyword_keeps_long_title_hit_in_top_six(tmp_path: Path) -> None:
    long_path = tmp_path / "lab-cps-open-lab-2026.md"
    long_path.write_text(
        """---
id: lab-cps-open-lab-2026
category: lab
title: サイバーフィジカルシステム研究室（CPS研） オープンキャンパス2026 出展
source_urls:
  - https://example.test/open-lab
retrieved_at: 2026-07-12
confidence: high
---

## 研究室公開・出展一覧
サイバーフィジカルシステム研究室では、人間タワーバトルなどの出展を行います。
""" + ("展示内容の詳しい説明です。" * 80),
        encoding="utf-8",
    )
    short_sections = "\n\n".join(
        f"## ブログ断片{i}\nサイバーフィジカルシステム研究室の短い紹介です。"
        for i in range(7)
    )
    short_path = tmp_path / "lab-cps-blog.md"
    short_path.write_text(
        f"""---
id: lab-cps-blog
category: lab
title: 研究室ブログ
source_urls:
  - https://example.test/blog
retrieved_at: 2026-07-12
confidence: high
---

{short_sections}
""",
        encoding="utf-8",
    )
    lexical = CampusLexicalSearch(tmp_path)

    hits = lexical.grep_sections(["サイバーフィジカルシステム研究室"])

    assert len(hits) == 6
    assert hits[0].chunk.file_id == "lab-cps-open-lab-2026"
    assert hits[0].title_heading_keyword_hit is True
    assert hits[0].body_length > hits[1].body_length


async def test_lexical_search_uses_keyword_variants_after_zero_primary_hits(tmp_path: Path) -> None:
    path = tmp_path / "lab.md"
    path.write_text(
        """---
id: lab
category: faculty
title: 研究室
source_urls:
  - https://example.test/lab
retrieved_at: 2026-07-11
confidence: high
---

## 研究室
サイバーフィジカルシステムを扱います。
""",
        encoding="utf-8",
    )
    lexical = CampusLexicalSearch(tmp_path)

    outcome = lexical.grep_sections_with_trace(["サイバーフィジカルシステム研究室"])

    assert outcome.variants_attempted is True
    assert "サイバーフィジカルシステム" in outcome.variant_keywords
    assert len(outcome.hits) == 1


async def test_analyze_parses_json_retrieval_queries() -> None:
    llm = FakeLLMClient(
        completions=[
            '{"retrieval_queries": ["食堂 メニュー", "カフェテリア 営業時間"], "keywords": ["カフェテリア"], "intent": "food"}'
        ]
    )
    agent = _agent(llm=llm)

    result = await agent._analyze({"question": "学食について教えて", "history": []})

    assert result == {
        "retrieval_queries": ["食堂 メニュー", "カフェテリア 営業時間"],
        "keywords": ["カフェテリア"],
    }
    assert llm.complete_calls[0]["temperature"] == 0.2
    assert llm.complete_calls[0]["max_tokens"] == 300


async def test_analyze_prompt_allows_core_nouns_and_six_keywords() -> None:
    agent = _agent()

    messages = agent._build_analyze_messages("サイバーフィジカルシステム研究室では、どんな出展がありますか？", [])
    system_prompt = messages[0]["content"]

    assert "質問が求める対象を表す中核名詞" in system_prompt
    assert "最大2語" in system_prompt
    assert "keywords は合計最大6語" in system_prompt
    assert "[\"サイバーフィジカルシステム研究室\", \"出展\"]" in system_prompt


async def test_analyze_falls_back_to_raw_question_on_parse_failure() -> None:
    llm = FakeLLMClient(completions=["not json"])
    agent = _agent(llm=llm)

    result = await agent._analyze({"question": "サークルは？", "history": []})

    assert result == {"retrieval_queries": ["サークルは？"], "keywords": []}


async def test_analyze_budget_preserves_history_and_truncates_current_question() -> None:
    agent = _agent(llm_context_window=1000)
    history = [
        {"role": "user", "content": "ANALYZE_HISTORY_USER 食堂の質問済み"},
        {"role": "assistant", "content": "ANALYZE_HISTORY_ASSISTANT 食堂の回答済み"},
    ]

    messages = agent._build_analyze_messages("CURRENT_QUESTION " + ("あ" * 2000), history)
    prompt_budget = 1000 - 300 - PROMPT_MARGIN_TOKENS
    combined = "\n".join(message["content"] for message in messages)

    assert _message_tokens(messages) <= prompt_budget
    assert messages[1] == history[0]
    assert messages[2] == history[1]
    assert "ANALYZE_HISTORY_USER" in combined
    assert "ANALYZE_HISTORY_ASSISTANT" in combined
    assert "CURRENT_QUESTION" in combined
    assert "あ" * 1000 not in combined


async def test_retrieve_searches_multiple_queries_dedupes_by_chunk_id_and_caps_results() -> None:
    llm = FakeLLMClient()
    shared_low = _chunk(id="shared", title="古いスコア", score=0.50)
    shared_high = _chunk(id="shared", title="高いスコア", score=0.95)
    store = FakeKnowledgeStore(
        {
            "食堂 メニュー": [shared_low, *[_chunk(id=f"a-{i}", score=0.80 - i / 100) for i in range(8)]],
            "カフェテリア 営業時間": [shared_high, *[_chunk(id=f"b-{i}", score=0.70 - i / 100) for i in range(8)]],
        }
    )
    agent = _agent(llm=llm, store=store)

    result = await agent._retrieve(
        {"question": "学食は？", "retrieval_queries": ["食堂 メニュー", "カフェテリア 営業時間"]}
    )

    assert [call["query"] for call in store.calls] == ["食堂 メニュー", "カフェテリア 営業時間"]
    assert all(call["limit"] == 8 for call in store.calls)
    assert len(result["knowledge_results"]) == 17
    assert result["knowledge_results"][0].id == "shared"
    assert result["knowledge_results"][0].title == "高いスコア"


async def test_retrieve_preserves_grep_metadata_when_vector_hit_has_higher_score() -> None:
    grep_chunk = _chunk(
        id="shared",
        title="全文検索ヒット",
        score=0.50,
        grep_hit=True,
        grep_keywords=("研究室",),
    )
    vector_chunk = _chunk(
        id="shared",
        title="ベクトル再検索ヒット",
        score=0.95,
        grep_keywords=("山口高康",),
    )
    store = FakeKnowledgeStore({"研究室 教員": [vector_chunk]})
    agent = _agent(store=store)

    result = await agent._retrieve(
        {
            "question": "CPS研究室の教員は？",
            "retrieval_queries": ["研究室 教員"],
            "knowledge_results": [grep_chunk],
        }
    )

    assert len(result["knowledge_results"]) == 1
    merged = result["knowledge_results"][0]
    assert merged.id == "shared"
    assert merged.title == "ベクトル再検索ヒット"
    assert merged.score == 0.95
    assert merged.grep_hit is True
    assert merged.grep_keywords == ("研究室", "山口高康")


async def test_retrieve_expands_same_file_sibling_chunks_with_limit_and_trace(tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.INFO, logger="agent.trace")
    lexical, chunks = _write_chunked_knowledge_file(tmp_path, section_count=16)
    direct_chunks = [
        replace(chunks[0], score=0.82),
        replace(chunks[3], score=0.75),
    ]
    store = FakeKnowledgeStore({"学生メンバー": direct_chunks})
    agent = _agent(store=store, lexical=lexical)

    result = await agent._retrieve(
        {
            "trace_id": "trace-expand",
            "question": "学生メンバーは？",
            "retrieval_queries": ["学生メンバー"],
        }
    )

    direct_ids = {chunk.id for chunk in direct_chunks}
    expanded = [chunk for chunk in result["knowledge_results"] if chunk.id not in direct_ids]
    expected_indices = [1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
    assert len(result["knowledge_results"]) == 14
    assert {chunk.id for chunk in direct_chunks}.issubset({chunk.id for chunk in result["knowledge_results"]})
    assert [chunk.chunk_index for chunk in expanded] == expected_indices
    assert [chunk.score for chunk in expanded] == pytest.approx([0.74] * 12)
    assert all(chunk.grep_hit is False for chunk in expanded)
    assert all(chunk.same_file_expanded is True for chunk in expanded)
    assert result["same_file_expanded_file_ids"] == ["lab-cps-members"]
    assert result["same_file_expanded_chunk_ids"] == [chunk.id for chunk in expanded]

    records = [json.loads(record.getMessage()) for record in caplog.records if record.name == "agent.trace"]
    expand_records = [record for record in records if record["event"] == "expand"]
    assert expand_records == [
        {
            "event": "expand",
            "trace_id": "trace-expand",
            "file_id": "lab-cps-members",
            "added_chunk_indices": expected_indices,
        }
    ]


async def test_retrieve_does_not_expand_single_same_file_hit(tmp_path: Path, caplog) -> None:
    caplog.set_level(logging.INFO, logger="agent.trace")
    lexical, chunks = _write_chunked_knowledge_file(tmp_path, section_count=6)
    direct_chunk = replace(chunks[0], score=0.88)
    agent = _agent(store=FakeKnowledgeStore({"学生メンバー": [direct_chunk]}), lexical=lexical)

    result = await agent._retrieve(
        {
            "trace_id": "trace-single",
            "question": "学生メンバーは？",
            "retrieval_queries": ["学生メンバー"],
        }
    )

    assert result["knowledge_results"] == [direct_chunk]
    assert result["same_file_expanded_file_ids"] == []
    assert result["same_file_expanded_chunk_ids"] == []
    records = [json.loads(record.getMessage()) for record in caplog.records if record.name == "agent.trace"]
    assert [record for record in records if record["event"] == "expand"] == []


async def test_same_file_expansion_uses_only_remaining_cap_slots(tmp_path: Path) -> None:
    lexical, chunks = _write_chunked_knowledge_file(tmp_path, section_count=20)
    same_file_direct = [
        replace(chunks[0], score=0.80),
        replace(chunks[1], score=0.79),
    ]
    other_direct = [
        _chunk(
            id=f"other-direct-{index}",
            title=f"直接ヒット{index}",
            score=0.98 - index / 1000,
            file_id=f"other-file-{index}",
            chunk_index=0,
        )
        for index in range(21)
    ]
    direct_chunks = [*same_file_direct, *other_direct]
    agent = _agent(store=FakeKnowledgeStore({"学生メンバー": direct_chunks}), lexical=lexical)

    result = await agent._retrieve(
        {
            "trace_id": "trace-cap",
            "question": "学生メンバーは？",
            "retrieval_queries": ["学生メンバー"],
        }
    )

    result_ids = {chunk.id for chunk in result["knowledge_results"]}
    direct_ids = {chunk.id for chunk in direct_chunks}
    expanded = [chunk for chunk in result["knowledge_results"] if chunk.id not in direct_ids]
    assert len(result["knowledge_results"]) == 24
    assert direct_ids.issubset(result_ids)
    assert len(expanded) == 1
    assert expanded[0].chunk_index == 2
    assert expanded[0].score == pytest.approx(0.78)
    assert expanded[0].same_file_expanded is True


async def test_same_file_expansion_is_idempotent_across_repeated_retrieve_merges(tmp_path: Path) -> None:
    lexical, chunks = _write_chunked_knowledge_file(tmp_path, section_count=16)
    direct_chunks = [
        replace(chunks[0], score=0.82),
        replace(chunks[3], score=0.75),
    ]
    agent = _agent(store=FakeKnowledgeStore({"学生メンバー": direct_chunks}), lexical=lexical)
    base_state = {
        "trace_id": "trace-idempotent",
        "question": "学生メンバーは？",
        "retrieval_queries": ["学生メンバー"],
    }

    first = await agent._retrieve(base_state)
    second = await agent._retrieve({**base_state, **first})

    assert [chunk.id for chunk in second["knowledge_results"]] == [
        chunk.id for chunk in first["knowledge_results"]
    ]
    assert second["same_file_expanded_file_ids"] == first["same_file_expanded_file_ids"]
    assert second["same_file_expanded_chunk_ids"] == first["same_file_expanded_chunk_ids"]
    assert len(second["knowledge_results"]) == 14


async def test_evaluate_insufficient_triggers_two_web_rounds_then_generates() -> None:
    llm = FakeLLMClient(
        completions=[
            '{"retrieval_queries": ["学長 秋田県立大学"], "intent": "leader"}',
            '{"sufficient": false, "missing": "学長名", "web_queries": ["秋田県立大学 学長"]}',
            '{"sufficient": false, "missing": "確認不足", "web_queries": ["秋田県立大学 学長 プロフィール"]}',
            '{"sufficient": false, "missing": "まだ不足", "web_queries": ["秋田県立大学 学長"]}',
        ],
        tokens=["最終回答"],
    )
    store = FakeKnowledgeStore([])
    search = FakeSearchProvider(
        [
            WebSearchResult("公式1", "https://example.test/page1", "snippet1"),
            WebSearchResult("公式2", "https://example.test/page2", "snippet2"),
        ]
    )
    http_factory = _http_factory(
        {
            "https://example.test/page1": "<html><main>公式ページ本文1</main></html>",
            "https://example.test/page2": "<html><main>公式ページ本文2</main></html>",
        }
    )
    agent = _agent(llm=llm, store=store, search=search, http_client_factory=http_factory)

    events = await _collect(agent, "学長は誰ですか？")

    status_steps = [payload["step"] for event, payload in events if event == "status"]
    assert status_steps == [
        "analyze",
        "retrieve",
        "search",
        "evaluate",
        "web_search",
        "evaluate",
        "web_search",
        "evaluate",
        "generate",
    ]
    assert [call["query"] for call in search.calls] == [
        "秋田県立大学 学長",
        "秋田県立大学 学長 プロフィール",
    ]
    assert [call["include_domains"] for call in search.calls] == [["akita-pu.ac.jp"], None]
    assert events[-2] == ("token", {"text": "最終回答"})
    assert llm.stream_calls[0]["temperature"] == 0.7


async def test_web_search_uses_include_domains_only_on_first_round() -> None:
    search = FakeSearchProvider(
        [
            WebSearchResult("公式1", "https://example.test/page1", "snippet1", "raw content 1"),
            WebSearchResult("公式2", "https://example.test/page2", "snippet2", "raw content 2"),
        ]
    )
    agent = _agent(search=search)
    state = {
        "question": "学長は誰ですか？",
        "keywords": ["学長"],
        "web_queries": ["秋田県立大学 学長"],
        "web_results": [],
        "web_search_rounds": 0,
        "used_web_queries": [],
        "used_web_query_keys": [],
    }

    state.update(await agent._web_search(state))
    state.update(await agent._web_search(state))

    assert [call["query"] for call in search.calls] == ["秋田県立大学 学長", "秋田県立大学 学長"]
    assert [call["include_domains"] for call in search.calls] == [["akita-pu.ac.jp"], None]


async def test_stream_emits_search_status_step() -> None:
    llm = FakeLLMClient(
        completions=[
            '{"retrieval_queries": ["サークル"], "keywords": ["サークル"], "intent": "clubs"}',
            '{"sufficient": true, "missing": "", "grep_keywords": [], "web_queries": []}',
        ],
        tokens=["回答"],
    )
    agent = _agent(llm=llm, store=FakeKnowledgeStore([]), lexical=FakeLexicalSearch())

    events = await _collect(agent, "サークルを教えて")

    status_steps = [payload["step"] for event, payload in events if event == "status"]
    assert status_steps == ["analyze", "retrieve", "search", "evaluate", "generate"]


async def test_web_page_fetch_and_extraction_drops_tags_and_truncates() -> None:
    long_text = "本文" + ("x" * 4100)
    html = f"""
    <html>
      <body>
        <nav>navigation should disappear</nav>
        <script>script should disappear</script>
        <style>style should disappear</style>
        <main>{long_text}</main>
      </body>
    </html>
    """
    agent = _agent(http_client_factory=_http_factory({"https://example.test/page": html}))

    text = await agent._fetch_page_text("https://example.test/page")

    assert "navigation should disappear" not in text
    assert "script should disappear" not in text
    assert "style should disappear" not in text
    assert text.startswith("本文")
    assert len(text) == 1400


async def test_fetch_search_results_uses_raw_content_without_http_fetch() -> None:
    fetch_calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        fetch_calls.append(str(request.url))
        return httpx.Response(500)

    agent = _agent(
        http_client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            timeout=8.0,
        )
    )
    result = WebSearchResult(
        "Raw page",
        "https://example.test/raw",
        "snippet",
        "先頭" + ("あ" * 1600) + "サイバーフィジカルシステム研究室 山口高康" + ("い" * 1600),
    )

    fetched = await agent._fetch_search_results(
        [result],
        keywords=["サイバーフィジカルシステム研究室", "山口高康"],
    )

    assert fetch_calls == []
    assert len(fetched) == 1
    assert fetched[0].text.startswith("…")
    assert "山口高康" in fetched[0].text


async def test_focused_extraction_centers_window_on_keyword_match() -> None:
    text = "先頭" + ("あ" * 1600) + "サイバーフィジカルシステム研究室 山口高康" + ("い" * 1600)

    excerpt = RealCampusAgent._focus_page_text(text, ["サイバーフィジカルシステム研究室", "山口高康"])

    assert excerpt.startswith("…")
    assert "サイバーフィジカルシステム研究室" in excerpt
    assert "山口高康" in excerpt
    assert "先頭" not in excerpt
    assert len(excerpt) <= 1401


async def test_context_budget_truncates_and_drops_knowledge_chunks_by_score() -> None:
    agent = _agent()
    high = _chunk(id="high", title="High score", score=0.99, text="HIGH_CONTEXT " + ("あ" * 1200))
    low = _chunk(id="low", title="Low score", score=0.10, text="LOW_CONTEXT " + ("い" * 1200))

    context = agent._assemble_context_with_budget([low, high], [], mode="generate", token_budget=100)

    assert estimate_tokens(context.text) <= 100
    assert [chunk.id for chunk in context.knowledge_results] == ["high"]
    assert "HIGH_CONTEXT" in context.text
    assert "LOW_CONTEXT" not in context.text
    assert len(context.text) < len(high.text)


async def test_context_packing_prioritizes_grep_hits_high_vector_web_then_remaining_vectors() -> None:
    agent = _agent()
    grep = _chunk(
        id="grep",
        title="Grep",
        score=0.10,
        text="GREP_CONTEXT",
        source_urls=["https://example.test/grep"],
        grep_hit=True,
        grep_keywords=("研究室",),
    )
    high_vector = _chunk(
        id="high-vector",
        title="High vector",
        score=0.60,
        text="HIGH_VECTOR_CONTEXT",
        source_urls=["https://example.test/high"],
    )
    low_vector = _chunk(
        id="low-vector",
        title="Low vector",
        score=0.59,
        text="LOW_VECTOR_CONTEXT",
        source_urls=["https://example.test/low"],
    )
    none_score_vector = _chunk(
        id="none-score-vector",
        title="None score vector",
        score=None,
        text="NONE_SCORE_VECTOR_CONTEXT",
        source_urls=["https://example.test/none"],
    )
    web = WebSearchResult("Web", "https://example.test/web", "snippet", "WEB_CONTEXT")

    context = agent._assemble_context_with_budget(
        [low_vector, high_vector, grep, none_score_vector],
        [web],
        mode="generate",
        token_budget=500,
    )

    assert context.text.index("GREP_CONTEXT") < context.text.index("HIGH_VECTOR_CONTEXT")
    assert context.text.index("HIGH_VECTOR_CONTEXT") < context.text.index("WEB_CONTEXT")
    assert context.text.index("WEB_CONTEXT") < context.text.index("LOW_VECTOR_CONTEXT")
    assert context.text.index("LOW_VECTOR_CONTEXT") < context.text.index("NONE_SCORE_VECTOR_CONTEXT")
    assert [chunk.id for chunk in context.knowledge_results] == [
        "grep",
        "high-vector",
        "low-vector",
        "none-score-vector",
    ]
    assert [result.url for result in context.web_results] == ["https://example.test/web"]


async def test_generation_budget_preserves_history_and_trims_context() -> None:
    agent = _agent(llm_context_window=1520, llm_answer_max_tokens=200)
    history = [
        {"role": "user", "content": "HISTORY_USER 食堂について聞いていました。"},
        {"role": "assistant", "content": "HISTORY_ASSISTANT 食堂はカフェテリア棟にあります。"},
    ]
    context_text = "HIGH_CONTEXT " + ("う" * 2400) + " END_CONTEXT"
    state = {
        "question": "食堂はどこですか？",
        "history": history,
        "knowledge_results": [
            _chunk(id="high", title="High score", score=0.99, text=context_text)
        ],
        "web_results": [],
    }

    messages, context = agent._build_generation_messages_with_sources(state)
    prompt_budget = 1520 - 200 - PROMPT_MARGIN_TOKENS
    combined = "\n".join(message["content"] for message in messages)

    assert _message_tokens(messages) <= prompt_budget
    assert messages[1] == history[0]
    assert messages[2] == history[1]
    assert "HISTORY_USER" in combined
    assert "HISTORY_ASSISTANT" in combined
    assert "HIGH_CONTEXT" in combined
    assert "END_CONTEXT" not in combined
    assert len(context.text) < len(context_text)


async def test_generation_budget_shrinks_history_to_250_to_preserve_minimum_context() -> None:
    agent = _agent(llm_context_window=2816, llm_answer_max_tokens=640)
    state = {
        "question": "施設について教えて",
        "history": _long_history("MIN_CONTEXT"),
        "knowledge_results": [_long_context_chunk()],
        "web_results": [],
    }

    messages, context = agent._build_generation_messages_with_sources(state)
    history_messages = messages[1:-1]

    assert _message_tokens(messages) <= 2816 - 640 - PROMPT_MARGIN_TOKENS
    assert len(history_messages) == 4
    assert [len(message["content"]) for message in history_messages] == [250, 250, 250, 250]
    assert estimate_tokens(context.text) >= MIN_GENERATION_CONTEXT_TOKENS
    assert "CTX_START" in context.text


async def test_generation_budget_uses_120_floor_and_accepts_sub_minimum_context() -> None:
    agent = _agent(llm_context_window=2120, llm_answer_max_tokens=640)
    state = {
        "question": "施設について教えて",
        "history": _long_history("LOW_CONTEXT"),
        "knowledge_results": [_long_context_chunk()],
        "web_results": [],
    }

    messages, context = agent._build_generation_messages_with_sources(state)
    history_messages = messages[1:-1]

    assert _message_tokens(messages) <= 2120 - 640 - PROMPT_MARGIN_TOKENS
    assert len(history_messages) == 4
    assert [len(message["content"]) for message in history_messages] == [120, 120, 120, 120]
    assert 0 < estimate_tokens(context.text) < MIN_GENERATION_CONTEXT_TOKENS
    assert "CTX_START" in context.text


async def test_forced_generation_budget_does_not_inflate_without_history_freed_tokens() -> None:
    agent = _agent(llm_context_window=2816, llm_answer_max_tokens=640)
    state = {
        "question": "施設について教えて",
        "history": [],
        "knowledge_results": [_long_context_chunk()],
        "web_results": [],
    }

    messages, context = agent._build_generation_messages_with_sources(state, token_budget=100)

    assert len(messages) == 2
    assert estimate_tokens(context.text) <= 100
    assert estimate_tokens(context.text) < MIN_GENERATION_CONTEXT_TOKENS
    assert "CTX_START" in context.text


async def test_web_context_is_truncated_to_remaining_budget() -> None:
    agent = _agent()
    result = WebSearchResult(
        "Web page",
        "https://example.test/web",
        "短いスニペット",
        "WEB_START " + ("う" * 1600) + " WEB_END",
    )

    context = agent._assemble_context_with_budget([], [result], mode="generate", token_budget=80)

    assert estimate_tokens(context.text) <= 80
    assert [web.url for web in context.web_results] == ["https://example.test/web"]
    assert "WEB_START" in context.text
    assert "WEB_END" not in context.text


async def test_evaluate_messages_use_summary_context_within_budget() -> None:
    agent = _agent(llm_context_window=1800)
    state = {
        "question": "施設について教えて",
        "knowledge_results": [_chunk(id="facility", title="施設", text="施設情報 " + ("あ" * 2000), score=0.9)],
        "web_results": [
            WebSearchResult("公式ページ", "https://example.test/facility", "snippet", "WEB_SUMMARY " + ("い" * 2000))
        ],
    }

    messages = agent._build_evaluate_messages(state)
    prompt_budget = 1800 - 300 - PROMPT_MARGIN_TOKENS
    combined = "\n".join(message["content"] for message in messages)

    assert _message_tokens(messages) <= prompt_budget
    assert "summary:" in combined
    assert "WEB_SUMMARY" in combined
    assert "い" * 700 not in combined


async def test_evaluate_messages_include_value_demand_criterion() -> None:
    agent = _agent()

    messages = agent._build_evaluate_messages(
        {
            "question": "サイバーフィジカルシステム研究室の先生は誰ですか？",
            "knowledge_results": [],
            "web_results": [],
        }
    )

    assert (
        "質問が特定の値（人名・数値・日時・場所・URL）を尋ねている場合、その値そのものがコンテキストに含まれていなければ、"
        "関連説明があっても必ず insufficient としてください。"
    ) in messages[0]["content"]


async def test_evaluate_uses_centered_summary_for_grep_hit_chunks() -> None:
    agent = _agent(llm_context_window=1400)
    chunk = _chunk(
        id="grep",
        title="研究室",
        text=("前" * 600) + "サイバーフィジカルシステム研究室 山口高康教授" + ("後" * 600),
        score=1.01,
        grep_hit=True,
        grep_keywords=("サイバーフィジカルシステム研究室",),
    )
    messages = agent._build_evaluate_messages(
        {
            "question": "先生は誰ですか？",
            "knowledge_results": [chunk],
            "web_results": [],
            "search_executed": True,
            "search_terms": ["サイバーフィジカルシステム研究室"],
            "search_hit_count": 1,
        }
    )
    combined = "\n".join(message["content"] for message in messages)

    assert "サイバーフィジカルシステム研究室 山口高康教授" in combined
    assert "前" * 500 not in combined


async def test_evaluate_retrieval_queries_trigger_one_reretrieve_and_skip_used_queries() -> None:
    llm = FakeLLMClient(
        completions=[
            '{"retrieval_queries": ["食堂"], "keywords": ["食堂"], "intent": "food"}',
            '{"sufficient": false, "missing": "営業時間", "grep_keywords": [], "retrieval_queries": ["カフェテリア 営業時間", "食堂"], "web_queries": ["食堂 営業時間"]}',
            '{"sufficient": true, "missing": "", "grep_keywords": [], "retrieval_queries": ["別クエリ"], "web_queries": []}',
        ],
        tokens=["回答"],
    )
    store = FakeKnowledgeStore(
        {
            "食堂": [_chunk(id="initial", title="食堂")],
            "カフェテリア 営業時間": [_chunk(id="followup", title="カフェテリア")],
        }
    )
    agent = _agent(llm=llm, store=store, lexical=FakeLexicalSearch())

    events = await _collect(agent, "食堂の営業時間は？")

    assert [call["query"] for call in store.calls] == ["食堂", "カフェテリア 営業時間"]
    status_payloads = [payload for event, payload in events if event == "status"]
    assert [payload["step"] for payload in status_payloads] == [
        "analyze",
        "retrieve",
        "search",
        "evaluate",
        "retrieve",
        "evaluate",
        "generate",
    ]
    assert status_payloads[4]["text"] == "観点を変えて資料を探し直しています…"


async def test_route_after_evaluate_prioritizes_search_retrieve_web_then_generate() -> None:
    agent = _agent()

    assert (
        agent._route_after_evaluate(
            {
                "sufficient": False,
                "grep_keywords": ["研究室"],
                "followup_retrieval_queries": ["研究室 教員"],
                "used_retrieval_queries": [],
                "local_search_followups": 0,
                "retrieval_followups": 0,
                "web_search_rounds": 0,
            }
        )
        == "search"
    )
    assert (
        agent._route_after_evaluate(
            {
                "sufficient": False,
                "grep_keywords": [],
                "followup_retrieval_queries": ["研究室 教員"],
                "used_retrieval_queries": [],
                "local_search_followups": 0,
                "retrieval_followups": 0,
                "web_search_rounds": 0,
            }
        )
        == "retrieve"
    )
    assert (
        agent._route_after_evaluate(
            {
                "sufficient": False,
                "grep_keywords": [],
                "followup_retrieval_queries": ["研究室 教員"],
                "used_retrieval_queries": [RealCampusAgent._retrieval_query_key("研究室 教員")],
                "local_search_followups": 0,
                "retrieval_followups": 0,
                "web_search_rounds": 0,
            }
        )
        == "web_search"
    )
    assert (
        agent._route_after_evaluate(
            {
                "sufficient": False,
                "grep_keywords": [],
                "followup_retrieval_queries": [],
                "used_retrieval_queries": [],
                "web_search_rounds": 3,
                "keywords": [],
            }
        )
        == "generate"
    )


async def test_give_up_gate_controls_investigation_log() -> None:
    agent = _agent()
    state = {
        "question": "不明な制度は？",
        "history": [],
        "knowledge_results": [],
        "web_results": [],
        "sufficient": False,
        "retrieve_executed": True,
        "search_executed": True,
        "retrieval_queries": ["不明な制度"],
        "search_terms": ["不明な制度"],
        "search_variant_terms": ["制度"],
        "web_search_rounds": 2,
        "used_web_queries": ["不明な制度", "不明な制度 秋田県立大学"],
    }

    messages = agent._build_generation_messages(state)
    combined = "\n".join(message["content"] for message in messages)
    assert "調査ログ:" in combined

    state["web_search_rounds"] = 1
    messages = agent._build_generation_messages(state)
    combined = "\n".join(message["content"] for message in messages)
    assert "調査ログ:" not in combined


async def test_generate_system_prompt_contains_deflection_ban_rule() -> None:
    llm = FakeLLMClient(
        completions=[
            '{"retrieval_queries": ["食堂"], "intent": "facility"}',
            '{"sufficient": true, "missing": "", "web_queries": []}',
        ]
    )
    store = FakeKnowledgeStore([_chunk()])
    agent = _agent(llm=llm, store=store)

    await _collect(agent, "食堂はどこですか？")

    system_prompt = llm.stream_calls[0]["messages"][0]["content"]
    assert system_prompt.startswith(GENERATE_SYSTEM_PROMPT)
    assert "丸投げする表現を回答の主内容にしない" in system_prompt
    assert "公式サイトでご確認ください" in system_prompt
    assert "学内ナレッジを優先" in system_prompt
    assert "誇張・改変しない" in system_prompt
    assert "時間コンテキスト:" in system_prompt
    assert "現在日時:" in system_prompt


async def test_real_agent_deduplicates_sources_from_generation_context() -> None:
    llm = FakeLLMClient(
        completions=[
            '{"retrieval_queries": ["施設"], "intent": "facility"}',
            '{"sufficient": true, "missing": "", "web_queries": []}',
        ],
        tokens=["回答"],
    )
    store = FakeKnowledgeStore(
        [
            _chunk(id="chunk-1", title="施設A", source_urls=["https://example.test/shared"]),
            _chunk(id="chunk-2", title="施設B", source_urls=["https://example.test/shared"]),
        ]
    )
    agent = _agent(llm=llm, store=store)

    events = await _collect(agent, "施設について教えて")

    assert events[-1][1]["sources"] == [
        {"title": "施設A", "url": "https://example.test/shared", "type": "knowledge"}
    ]


async def test_generate_uses_answer_max_tokens_setting() -> None:
    llm = FakeLLMClient(
        completions=[
            '{"retrieval_queries": ["食堂"], "intent": "facility"}',
            '{"sufficient": true, "missing": "", "web_queries": []}',
        ],
        tokens=["回答"],
    )
    agent = _agent(llm=llm, store=FakeKnowledgeStore([_chunk()]), llm_answer_max_tokens=321)

    await _collect(agent, "食堂はどこですか？")

    assert llm.stream_calls[0]["max_tokens"] == 321


async def test_generation_preverify_rebuilds_over_budget_prompt_with_reduced_context() -> None:
    llm = FakeLLMClient(
        completions=[
            '{"retrieval_queries": ["施設"], "intent": "facility"}',
            '{"sufficient": true, "missing": "", "web_queries": []}',
        ],
        token_counts=[1400, 800],
        tokens=["回答"],
    )
    store = FakeKnowledgeStore(
        [_chunk(id="long", title="長い根拠", text="CONTEXT_START " + ("秋田県立大学" * 400), score=0.99)]
    )
    agent = _agent(llm=llm, store=store, llm_context_window=1520, llm_answer_max_tokens=200)
    history = [
        {"role": "user", "content": "PRESERVED_HISTORY_USER 施設の場所を聞いていました。"},
        {"role": "assistant", "content": "PRESERVED_HISTORY_ASSISTANT 施設案内を続けています。"},
    ]

    await _collect(agent, "施設について教えて", history=history)

    streamed_prompt = "\n\n".join(message["content"] for message in llm.stream_calls[0]["messages"])
    assert len(llm.count_token_texts) == 2
    assert len(llm.count_token_texts[1]) < len(llm.count_token_texts[0])
    assert streamed_prompt == llm.count_token_texts[1]
    assert "PRESERVED_HISTORY_USER" in streamed_prompt
    assert "PRESERVED_HISTORY_ASSISTANT" in streamed_prompt


async def test_generation_retries_context_length_bad_request_once_with_smaller_context() -> None:
    llm = RetryLLMClient(
        completions=[
            '{"retrieval_queries": ["施設"], "intent": "facility"}',
            '{"sufficient": true, "missing": "", "web_queries": []}',
        ]
    )
    store = FakeKnowledgeStore(
        [_chunk(id="long", title="長い根拠", text="CONTEXT_START " + ("本荘キャンパス" * 400), score=0.99)]
    )
    agent = _agent(llm=llm, store=store, llm_context_window=1520, llm_answer_max_tokens=200)
    history = [
        {"role": "user", "content": "RETRY_HISTORY_USER 施設の概要を質問済みです。"},
        {"role": "assistant", "content": "RETRY_HISTORY_ASSISTANT 続けて確認します。"},
    ]

    events = await _collect(agent, "施設について教えて", history=history)

    first_prompt = "\n\n".join(message["content"] for message in llm.stream_calls[0]["messages"])
    retry_prompt = "\n\n".join(message["content"] for message in llm.stream_calls[1]["messages"])
    assert events[-2] == ("token", {"text": "retry ok"})
    assert len(llm.stream_calls) == 2
    assert len(retry_prompt) < len(first_prompt)
    assert "RETRY_HISTORY_USER" in first_prompt
    assert "RETRY_HISTORY_ASSISTANT" in first_prompt
    assert "RETRY_HISTORY_USER" in retry_prompt
    assert "RETRY_HISTORY_ASSISTANT" in retry_prompt


async def test_agent_trace_logs_structured_json_lines(caplog, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_TRACE", "1")
    caplog.set_level(logging.INFO, logger="agent.trace")
    vector_chunk = _chunk(
        id="vector",
        title="ベクトル",
        text="ベクトル根拠",
        score=0.91,
        file_id="file-vector",
        chunk_index=2,
    )
    grep_chunk = _chunk(
        id="grep",
        title="全文検索",
        text="全文検索根拠",
        score=1102.0,
        file_id="file-grep",
        chunk_index=3,
        grep_hit=True,
        grep_keywords=("出展",),
    )
    lexical = FakeLexicalSearch(
        LexicalSearchOutcome(
            hits=[
                SectionHit(
                    chunk=grep_chunk,
                    distinct_keyword_hits=1,
                    title_heading_keyword_hit=True,
                    total_hits=2,
                    body_length=len(grep_chunk.text),
                )
            ],
            searched_keywords=["出展"],
            variant_keywords=[],
            variants_attempted=False,
        )
    )
    llm = FakeLLMClient(
        completions=[
            '{"retrieval_queries": ["CPS研 出展"], "keywords": ["CPS研", "出展"], "intent": "event"}',
            '{"sufficient": false, "missing": "URL確認", "grep_keywords": [], "retrieval_queries": [], "web_queries": ["CPS研 出展"]}',
            '{"sufficient": true, "missing": "", "grep_keywords": [], "retrieval_queries": [], "web_queries": []}',
        ],
        token_counts=[512],
        tokens=["回答"],
    )
    search = FakeSearchProvider(
        [
            WebSearchResult(
                "CPS研 出展",
                "https://example.test/open-lab",
                "snippet",
                "CPS研の出展本文",
            )
        ]
    )
    agent = _agent(
        llm=llm,
        store=FakeKnowledgeStore([vector_chunk]),
        search=search,
        lexical=lexical,
    )

    await _collect(agent, "CPS研の出展は？")

    records = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "agent.trace"
    ]
    events = [record["event"] for record in records]
    assert events == ["analyze", "retrieve", "search", "evaluate", "web_search", "evaluate", "generate"]

    retrieve = next(record for record in records if record["event"] == "retrieve")
    assert retrieve["queries"][0]["hits"] == [
        {"file_id": "file-vector", "chunk_index": 2, "score": 0.91}
    ]
    search_record = next(record for record in records if record["event"] == "search")
    assert search_record["hits"] == [
        {"file_id": "file-grep", "chunk_index": 3, "distinct": 1, "total": 2}
    ]
    web = next(record for record in records if record["event"] == "web_search")
    assert web["queries"] == ["CPS研 出展"]
    assert web["urls"] == ["https://example.test/open-lab"]
    generate = records[-1]
    assert generate["adopted_chunk_ids"]
    assert "rejected_chunk_ids" in generate
    assert generate["prompt_tokens"] == 512


async def test_agent_trace_can_be_disabled(caplog, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_TRACE", "0")
    caplog.set_level(logging.INFO, logger="agent.trace")
    llm = FakeLLMClient(
        completions=[
            '{"retrieval_queries": ["食堂"], "keywords": ["食堂"], "intent": "facility"}',
            '{"sufficient": true, "missing": "", "web_queries": []}',
        ],
        tokens=["回答"],
    )
    agent = _agent(llm=llm, store=FakeKnowledgeStore([_chunk()]), lexical=FakeLexicalSearch())

    await _collect(agent, "食堂はどこ？")

    assert [record for record in caplog.records if record.name == "agent.trace"] == []
