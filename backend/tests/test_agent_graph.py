from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest
import httpx
from openai import BadRequestError

from app.agent.campus_map import resolve_location
from app.agent.graph import (
    DECIDE_SYSTEM_PROMPT,
    GENERATE_SYSTEM_PROMPT,
    HARD_CONTEXT_RATIO,
    LOCATION_INDEX_SOURCE,
    MAX_HISTORY_MESSAGES,
    MIN_GENERATION_CONTEXT_TOKENS,
    PROMPT_MARGIN_TOKENS,
    SOFT_CONTEXT_RATIO,
    RealCampusAgent,
    _ContextAssembly,
    estimate_tokens,
)
from app.models.chat import Source
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
        self.decide_calls: list[dict] = []
        self.stream_calls: list[dict] = []
        self.count_token_texts: list[str] = []

    async def decide(self, messages, schema) -> str:
        self.decide_calls.append({"messages": messages, "schema": schema})
        if self.completions:
            return self.completions.pop(0)
        return json.dumps(
            {
                "thought": "根拠を確認しました。",
                "action": "finish",
                "action_input": {"reason": "完了"},
            },
            ensure_ascii=False,
        )

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
    ):
        self.stream_calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
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
    ):
        self.stream_calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
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

    async def search(
        self,
        query: str,
        *,
        max_results: int,
        include_domains=None,
        include_raw_content: bool = True,
    ):
        self.calls.append(
            {
                "query": query,
                "max_results": max_results,
                "include_domains": include_domains,
                "include_raw_content": include_raw_content,
            }
        )
        offset = (len(self.calls) - 1) * max_results
        rows = self.results[offset : offset + max_results] or self.results[:max_results]
        return rows[:max_results]


class FailingSearchProvider:
    available = True

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def search(
        self,
        query: str,
        *,
        max_results: int,
        include_domains=None,
        include_raw_content: bool = True,
    ):
        self.calls.append(
            {
                "query": query,
                "max_results": max_results,
                "include_domains": include_domains,
                "include_raw_content": include_raw_content,
            }
        )
        raise RuntimeError("search unavailable")


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
    llm_context_window: int = 16384,
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


def _decision(action: str, action_input: dict, thought: str = "次の手段を確認します。") -> str:
    return json.dumps(
        {"thought": thought, "action": action, "action_input": action_input},
        ensure_ascii=False,
    )


def _long_history(prefix: str = "HISTORY") -> list[dict[str, str]]:
    return [
        {"role": "user", "content": f"{prefix}_USER_1 " + ("あ" * 600)},
        {"role": "assistant", "content": f"{prefix}_ASSISTANT_1 " + ("い" * 600)},
        {"role": "user", "content": f"{prefix}_USER_2 " + ("う" * 600)},
        {"role": "assistant", "content": f"{prefix}_ASSISTANT_2 " + ("え" * 600)},
        {"role": "user", "content": f"{prefix}_USER_3 " + ("お" * 600)},
        {"role": "assistant", "content": f"{prefix}_ASSISTANT_3 " + ("か" * 600)},
        {"role": "user", "content": f"{prefix}_USER_4 " + ("き" * 600)},
        {"role": "assistant", "content": f"{prefix}_ASSISTANT_4 " + ("く" * 600)},
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


async def test_compiled_graph_matches_react_runtime() -> None:
    graph = _agent()._graph.get_graph()
    runtime_nodes = set(graph.nodes) - {"__start__", "__end__"}
    edges = {(edge.source, edge.target) for edge in graph.edges}

    assert runtime_nodes == {
        "decide",
        "retrieve",
        "search",
        "web_search",
        "campus_navigator",
        "ask_user",
        "respond_need_origin",
        "generate",
    }
    assert ("__start__", "decide") in edges
    assert ("retrieve", "decide") in edges
    assert ("search", "decide") in edges
    assert ("web_search", "decide") in edges
    assert ("ask_user", "__end__") in edges
    assert ("respond_need_origin", "__end__") in edges
    assert ("generate", "__end__") in edges


async def test_decide_prompt_is_the_fable_confirmed_text() -> None:
    assert DECIDE_SYSTEM_PROMPT.startswith(
        "あなたは秋田県立大学 本荘キャンパス（秋田県由利本荘市）の"
    )
    assert "本学を「APU」と略さないこと" in DECIDE_SYSTEM_PROMPT
    assert "web_search {queries: string[1..3]}" in DECIDE_SYSTEM_PROMPT
    assert "ツール実行 0 回のまま finish しない" in DECIDE_SYSTEM_PROMPT


async def test_decide_uses_scripted_transport_and_action_schema() -> None:
    llm = FakeLLMClient(
        completions=[_decision("retrieve", {"queries": ["食堂", "カフェテリア"]})]
    )
    agent = _agent(llm=llm)

    result = await agent._decide(
        {
            "question": "食堂について教えて",
            "history": [],
            "knowledge_results": [],
            "web_results": [],
            "decision_count": 0,
            "actions_log": [],
            "action_keys": [],
            "observations": [],
            "tool_executions": 0,
        }
    )

    assert result["action"] == "retrieve"
    assert result["action_input"] == {"queries": ["食堂", "カフェテリア"]}
    schema = llm.decide_calls[0]["schema"]
    assert schema["properties"]["action"]["enum"] == [
        "retrieve",
        "search",
        "web_search",
        "campus_navigator",
        "ask_user",
        "finish",
    ]
    assert llm.decide_calls[0]["messages"][0]["content"].startswith(DECIDE_SYSTEM_PROMPT)


async def test_decide_keeps_tolerant_json_object_parser_as_transport_floor() -> None:
    wrapped = (
        "判断結果です。\n```json\n"
        f"{_decision('search', {'keywords': ['GI512']})}"
        "\n```"
    )
    agent = _agent(llm=FakeLLMClient(completions=[wrapped]))

    result = await agent._decide(
        {
            "question": "GI512はどこ",
            "history": [],
            "knowledge_results": [],
            "web_results": [],
            "decision_count": 0,
            "actions_log": [],
            "action_keys": [],
            "observations": [],
            "tool_executions": 0,
        }
    )

    assert result["action"] == "search"
    assert result["action_input"] == {"keywords": ["GI512"]}


async def test_tool_zero_finish_is_returned_as_error_observation() -> None:
    llm = FakeLLMClient(
        completions=[_decision("finish", {"reason": "十分"})]
    )
    agent = _agent(llm=llm)

    result = await agent._decide(
        {
            "question": "食堂は？",
            "history": [],
            "knowledge_results": [],
            "web_results": [],
            "decision_count": 0,
            "actions_log": [],
            "action_keys": [],
            "observations": [],
            "tool_executions": 0,
        }
    )

    assert result["action"] == "decide"
    assert "ツール実行 0 回" in result["observations"][-1]
    assert result["action_keys"] == []


async def test_duplicate_action_is_not_reexecuted() -> None:
    decision = _decision("search", {"keywords": ["GI512"]})
    llm = FakeLLMClient(completions=[decision, decision])
    agent = _agent(llm=llm)
    state = {
        "question": "GI512はどこ",
        "history": [],
        "knowledge_results": [],
        "web_results": [],
        "decision_count": 0,
        "actions_log": [],
        "action_keys": [],
        "observations": [],
        "tool_executions": 0,
    }
    first = await agent._decide(state)
    second = await agent._decide({**state, **first, "tool_executions": 1})

    assert first["action"] == "search"
    assert second["action"] == "decide"
    assert "試行済み" in second["observations"][-1]
    assert len(second["action_keys"]) == 1


async def test_invalid_action_input_is_observed_without_execution() -> None:
    llm = FakeLLMClient(
        completions=[_decision("retrieve", {"queries": []})]
    )
    agent = _agent(llm=llm)

    result = await agent._decide(
        {
            "question": "質問",
            "history": [],
            "knowledge_results": [],
            "web_results": [],
            "decision_count": 0,
            "actions_log": [],
            "action_keys": [],
            "observations": [],
            "tool_executions": 0,
        }
    )

    assert result["action"] == "decide"
    assert "1〜3" in result["observations"][-1]


async def test_thought_sanitizer_rejects_internal_json() -> None:
    assert RealCampusAgent._sanitize_thought('{"action":"retrieve"}') == (
        "集めた情報をチェックしています…"
    )
    assert RealCampusAgent._sanitize_thought("資料の根拠を確認します。") == (
        "資料の根拠を確認します。"
    )


async def test_normal_retrieve_finish_stream_is_contract_compatible() -> None:
    chunk = _chunk()
    llm = FakeLLMClient(
        completions=[
            _decision("retrieve", {"queries": ["食堂"]}, "学内資料を探します。"),
            _decision("finish", {"reason": "根拠がそろった"}, "根拠を確認できました。"),
        ],
        tokens=["食堂", "です。"],
    )
    store = FakeKnowledgeStore([chunk])
    events = await _collect(_agent(llm=llm, store=store), "食堂について教えて")

    event_names = [event for event, _ in events]
    status_steps = [data["step"] for event, data in events if event == "status"]
    assert status_steps == ["analyze", "retrieve", "evaluate", "generate"]
    assert event_names[-1] == "done"
    assert "".join(data["text"] for event, data in events if event == "token") == "食堂です。"
    assert events[-1][1]["sources"] == [
        {"title": "食堂", "url": "https://example.test/facility", "type": "knowledge"}
    ]
    assert store.calls == [{"query": "食堂", "limit": 8}]


async def test_search_tool_stream_uses_search_step() -> None:
    grep_chunk = _chunk(grep_hit=True, grep_keywords=("GI512",), score=1001.0)
    lexical = FakeLexicalSearch(
        LexicalSearchOutcome(
            hits=[
                SectionHit(
                    chunk=grep_chunk,
                    distinct_keyword_hits=1,
                    title_heading_keyword_hit=True,
                    total_hits=1,
                    body_length=len(grep_chunk.text),
                )
            ],
            searched_keywords=["GI512"],
            variant_keywords=[],
            variants_attempted=False,
        )
    )
    llm = FakeLLMClient(
        completions=[
            _decision("search", {"keywords": ["GI512"]}),
            _decision("finish", {"reason": "発見"}),
        ],
        tokens=["回答"],
    )

    events = await _collect(_agent(llm=llm, lexical=lexical), "GI512はどこ")

    assert "search" in [data["step"] for event, data in events if event == "status"]
    assert lexical.calls == [["GI512"]]


async def test_retrieve_dedupes_chunks_and_preserves_grep_metadata() -> None:
    grep = _chunk(
        id="same",
        score=1001.0,
        grep_hit=True,
        grep_keywords=("食堂",),
    )
    vector = _chunk(id="same", score=0.95)
    agent = _agent(store=FakeKnowledgeStore([vector]))
    state = {
        "question": "食堂",
        "action_input": {"queries": ["食堂"]},
        "knowledge_results": [grep],
        "observations": [],
        "actions_log": [{"action": "retrieve", "result": "selected"}],
        "tool_executions": 0,
    }

    result = await agent._retrieve(state)

    assert len(result["knowledge_results"]) == 1
    merged = result["knowledge_results"][0]
    assert merged.grep_hit is True
    assert merged.grep_keywords == ("食堂",)
    assert merged.score == 1001.0


async def test_retrieve_expands_same_file_siblings_once(tmp_path: Path) -> None:
    path = tmp_path / "document.md"
    path.write_text(
        "---\nid: doc\ncategory: facility\ntitle: 施設\n"
        "source_urls: [https://example.test/doc]\nconfidence: high\n---\n"
        "## A\n本文A\n## B\n本文B\n## C\n本文C\n",
        encoding="utf-8",
    )
    lexical = CampusLexicalSearch(tmp_path)
    sections = lexical._load_sections()
    direct = [
        replace(sections[0].chunk, score=0.9),
        replace(sections[1].chunk, score=0.8),
    ]
    agent = _agent(store=FakeKnowledgeStore(direct), lexical=lexical)
    state = {
        "trace_id": "trace",
        "question": "施設",
        "action_input": {"queries": ["施設"]},
        "knowledge_results": [],
        "observations": [],
        "actions_log": [{"action": "retrieve", "result": "selected"}],
        "tool_executions": 0,
        "same_file_expanded_file_ids": [],
        "same_file_expanded_chunk_ids": [],
    }

    first = await agent._retrieve(state)
    second = await agent._retrieve(
        {
            **state,
            **first,
            "action_input": {"queries": ["別観点"]},
            "actions_log": [{"action": "retrieve", "result": "selected"}],
        }
    )

    assert len(first["knowledge_results"]) == 3
    assert first["same_file_expanded_file_ids"] == ["doc"]
    assert len(second["knowledge_results"]) == 3


async def test_web_search_is_always_unrestricted() -> None:
    search = FakeSearchProvider(
        [WebSearchResult("交通", "https://example.test/access", "案内", "本文")]
    )
    agent = _agent(search=search)
    result = await agent._web_search(
        {
            "question": "駅からの交通",
            "action_input": {"queries": ["羽後本荘駅 交通"]},
            "web_results": [],
            "observations": [],
            "actions_log": [{"action": "web_search", "result": "selected"}],
            "tool_executions": 0,
            "context_usage": {"soft_exceeded": False},
        }
    )

    assert result["web_results"][0].url == "https://example.test/access"
    assert search.calls[0]["include_domains"] is None
    assert search.calls[0]["include_raw_content"] is True


async def test_soft_budget_suppresses_web_raw_content_and_page_fetch() -> None:
    search = FakeSearchProvider(
        [WebSearchResult("交通", "https://example.test/access", "短い案内", "")]
    )

    def forbidden_http_factory():
        raise AssertionError("soft budget must not fetch pages")

    agent = _agent(search=search, http_client_factory=forbidden_http_factory)
    result = await agent._web_search(
        {
            "question": "交通",
            "action_input": {"queries": ["交通"]},
            "web_results": [],
            "observations": [],
            "actions_log": [{"action": "web_search", "result": "selected"}],
            "tool_executions": 0,
            "context_usage": {"soft_exceeded": True},
        }
    )

    assert search.calls[0]["include_raw_content"] is False
    assert result["web_results"][0].text == "短い案内"


async def test_tavily_unavailable_becomes_observation() -> None:
    search = FakeSearchProvider([])
    search.available = False
    agent = _agent(search=search)

    result = await agent._web_search(
        {
            "question": "最新情報",
            "action_input": {"queries": ["最新情報"]},
            "web_results": [],
            "observations": [],
            "actions_log": [{"action": "web_search", "result": "selected"}],
            "tool_executions": 0,
        }
    )

    assert "現在利用不可" in result["observations"][-1]
    assert result["tool_executions"] == 1
    assert search.calls == []


async def test_tool_failure_degrades_and_reaches_generate() -> None:
    class FailingStore:
        async def search(self, query: str, *, limit: int):
            raise RuntimeError("down")

    llm = FakeLLMClient(
        completions=[
            _decision("retrieve", {"queries": ["食堂"]}),
            _decision("finish", {"reason": "縮退して回答"}),
        ],
        tokens=["縮退回答"],
    )
    events = await _collect(
        _agent(llm=llm, store=FailingStore()),
        "食堂について教えて",
    )

    assert events[-1][0] == "done"
    assert "".join(data["text"] for event, data in events if event == "token") == "縮退回答"


async def test_web_failure_degrades_and_reaches_generate() -> None:
    llm = FakeLLMClient(
        completions=[
            _decision("web_search", {"queries": ["最新情報"]}),
            _decision("finish", {"reason": "縮退"}),
        ],
        tokens=["回答"],
    )
    events = await _collect(
        _agent(llm=llm, search=FailingSearchProvider()),
        "最新情報",
    )
    assert events[-1][0] == "done"


async def test_campus_navigator_fast_path_need_origin_exact_sse() -> None:
    llm = FakeLLMClient(
        completions=[
            _decision(
                "campus_navigator",
                {"request": "D414への経路を調べる"},
                "経路機構に任せます。",
            )
        ]
    )
    events = await _collect(_agent(llm=llm), "D414 に行きたい")

    names = [event for event, _ in events]
    assert names[-4:] == ["status", "token", "map", "done"]
    assert events[-3][1]["text"] == (
        "いまいる場所をマップでタップして教えてください！"
        "そこからの行き方をご案内します🗺️"
    )
    assert events[-2][1]["mode"] == "ask_origin"
    assert events[-1][1]["sources"] == [LOCATION_INDEX_SOURCE.model_dump()]
    assert len(llm.decide_calls) == 1


async def test_campus_navigator_route_map_is_after_all_tokens() -> None:
    llm = FakeLLMClient(
        completions=[
            _decision(
                "campus_navigator",
                {"request": "食堂からD414への経路"},
            ),
            _decision("finish", {"reason": "経路解決"}),
        ],
        tokens=["経路", "回答"],
    )
    events = await _collect(_agent(llm=llm), "食堂から D414 への行き方")

    token_indices = [index for index, item in enumerate(events) if item[0] == "token"]
    map_index = next(index for index, item in enumerate(events) if item[0] == "map")
    assert map_index > max(token_indices)
    assert events[map_index][1]["mode"] == "route"
    assert events[map_index][1]["path"]["edges"] == ["E6a", "E1"]
    assert events[-1][1]["sources"] == [LOCATION_INDEX_SOURCE.model_dump()]


async def test_campus_navigator_place_fast_path_and_location_fact() -> None:
    llm = FakeLLMClient(
        completions=[
            _decision(
                "campus_navigator",
                {"request": "情報ネットワーク研究室の場所"},
            ),
            _decision("finish", {"reason": "場所解決"}),
        ],
        tokens=["場所回答"],
    )
    agent = _agent(llm=llm)

    events = await _collect(agent, "情報ネットワーク研究室はどこ？")

    map_payload = next(data for event, data in events if event == "map")
    generation_user = llm.stream_calls[0]["messages"][-1]["content"]
    assert map_payload["mode"] == "place"
    assert map_payload["destination"]["room"] == "GI512"
    assert "情報ネットワーク研究室: GI512 — 学部棟Ⅰ / 5階" in generation_user


async def test_navigator_place_fast_path_excludes_declared_origin_from_destination() -> None:
    navigator = _agent().navigator

    result = await navigator.navigate(
        request="体育館の場所",
        question="現在地は食堂です。体育館はどこ？",
        history=[],
    )

    assert result["type"] == "place"
    assert result["destination"].node == "gym"
    assert result["fast_path"] is True


async def test_history_origin_is_used_without_reasking() -> None:
    history = [
        {
            "role": "user",
            "content": "現在地はカフェテリア（食堂）です。D414に行きたい",
            "map": {
                "mode": "origin_select",
                "origin": {"node": "cafeteria", "label": "カフェテリア（食堂）"},
            },
        },
        {"role": "assistant", "content": "経路をご案内しました。"},
    ]
    llm = FakeLLMClient(
        completions=[
            _decision(
                "campus_navigator",
                {"request": "体育館への経路"},
            ),
            _decision("finish", {"reason": "解決"}),
        ],
        tokens=["回答"],
    )

    events = await _collect(_agent(llm=llm), "じゃあ体育館は？", history=history)

    map_payload = next(data for event, data in events if event == "map")
    assert map_payload["mode"] == "route"
    assert map_payload["origin"]["node"] == "cafeteria"
    assert map_payload["destination"]["node"] == "gym"
    assert "直前の会話から継承" in llm.stream_calls[0]["messages"][-1]["content"]


async def test_unresolved_navigation_returns_to_main_decide() -> None:
    llm = FakeLLMClient(
        completions=[
            _decision("campus_navigator", {"request": "羽後本荘駅から空港への経路"}),
            _decision("resolve_place", {"expression": "羽後本荘駅", "role": "origin"}),
            _decision("resolve_place", {"expression": "空港", "role": "destination"}),
            _decision("ask_origin", {"destination": "空港"}),
            _decision("web_search", {"queries": ["羽後本荘駅 空港 交通"]}),
            _decision("finish", {"reason": "検索完了"}),
        ],
        tokens=["交通回答"],
    )
    search = FakeSearchProvider(
        [WebSearchResult("交通", "https://example.test/transport", "案内", "本文")]
    )

    events = await _collect(_agent(llm=llm, search=search), "羽後本荘駅から空港へ")

    assert search.calls
    assert not any(event == "map" for event, _ in events)
    assert events[-1][0] == "done"


async def test_navigator_ask_origin_validator_rejects_known_origin_then_routes() -> None:
    llm = FakeLLMClient(
        completions=[
            _decision("ask_origin", {"destination": "D414"}),
            _decision("find_route", {"origin": "食堂", "destination": "D414"}),
        ]
    )
    navigator = _agent(llm=llm).navigator

    result = await navigator.navigate(
        request="目的地まで案内",
        question="現在地は食堂です。そこへ行きたい",
        history=[],
    )

    assert result["type"] == "route"
    assert result["trace"][0]["action"] == "ask_origin"
    assert result["trace"][0]["thought"]
    assert "出発地は既知" in result["trace"][0]["observation"]
    assert result["map_payload"]["origin"]["node"] == "cafeteria"


async def test_navigator_ask_origin_validator_rejects_unresolved_destination() -> None:
    llm = FakeLLMClient(
        completions=[
            _decision("ask_origin", {"destination": "不明会場"}),
            _decision("ask_origin", {"destination": "不明会場"}),
            _decision("ask_origin", {"destination": "不明会場"}),
        ]
    )
    result = await _agent(llm=llm).navigator.navigate(
        request="不明会場への経路",
        question="そこに行きたい",
        history=[],
    )

    assert result["type"] == "not_navigable"
    assert len(result["trace"]) == 3
    assert all("目的地を特定できない" in item["observation"] for item in result["trace"])


async def test_ask_user_is_terminal_and_records_clarification_metadata() -> None:
    llm = FakeLLMClient(
        completions=[
            _decision(
                "ask_user",
                {"question": "参加したい学科は決まっていますか？"},
            )
        ]
    )
    agent = _agent(llm=llm)

    events = await _collect(agent, "おすすめを教えて")

    assert [data["step"] for event, data in events if event == "status"] == [
        "analyze",
        "generate",
    ]
    assert "".join(data["text"] for event, data in events if event == "token") == (
        "参加したい学科は決まっていますか？"
    )
    assert events[-1][1]["sources"] == []
    assert agent.consume_message_metadata("message-1") == {"kind": "clarification"}


async def test_previous_clarification_removes_ask_user_from_menu() -> None:
    llm = FakeLLMClient(
        completions=[_decision("retrieve", {"queries": ["情報工学科"]})]
    )
    agent = _agent(llm=llm)
    state = {
        "question": "情報工学科です",
        "history": [
            {
                "role": "assistant",
                "content": "学科は決まっていますか？",
                "metadata": {"kind": "clarification"},
            }
        ],
        "knowledge_results": [],
        "web_results": [],
        "decision_count": 0,
        "actions_log": [],
        "action_keys": [],
        "observations": [],
        "tool_executions": 0,
        "clarification_blocked": True,
    }

    await agent._decide(state)

    assert "ask_user" not in llm.decide_calls[0]["schema"]["properties"]["action"]["enum"]


async def test_context_thresholds_are_ratios_of_effective_window() -> None:
    class FixedCountLLM(FakeLLMClient):
        def __init__(self, count: int):
            super().__init__(completions=[_decision("finish", {"reason": "予算"})])
            self.count = count

        async def count_tokens(self, text: str) -> int | None:
            return self.count

    window = 1000
    llm = FixedCountLLM(850)
    agent = _agent(
        llm=llm,
        llm_context_window=window,
        llm_answer_max_tokens=100,
    )
    state = {
        "question": "質問",
        "history": [],
        "knowledge_results": [],
        "web_results": [],
        "decision_count": 1,
        "actions_log": [{"action": "retrieve", "result": "1件"}],
        "action_keys": ["retrieve\t{}"],
        "observations": ["1件"],
        "tool_executions": 1,
    }

    result = await agent._decide(state)

    assert SOFT_CONTEXT_RATIO == 0.70
    assert HARD_CONTEXT_RATIO == 0.85
    assert result["context_usage"]["hard_exceeded"] is True
    assert llm.decide_calls[0]["schema"]["properties"]["action"]["enum"] == [
        "finish",
        "ask_user",
    ]


async def test_token_counter_falls_back_to_estimator() -> None:
    agent = _agent(llm=FakeLLMClient())
    count, actual = await agent._count_text_tokens("秋田県立大学")
    assert count == estimate_tokens("秋田県立大学")
    assert actual is False


async def test_evidence_full_shrinks_action_menu() -> None:
    chunk = _chunk(text="根拠" * 5000)
    llm = FakeLLMClient(
        completions=[_decision("finish", {"reason": "十分"})]
    )
    agent = _agent(
        llm=llm,
        llm_context_window=1800,
        llm_answer_max_tokens=300,
    )
    state = {
        "question": "質問",
        "history": [],
        "knowledge_results": [chunk],
        "web_results": [],
        "decision_count": 1,
        "actions_log": [{"action": "retrieve", "result": "1件"}],
        "action_keys": ["retrieve\t{}"],
        "observations": ["1件"],
        "tool_executions": 1,
    }

    result = await agent._decide(state)

    assert result["context_usage"]["evidence_full"] is True
    assert llm.decide_calls[0]["schema"]["properties"]["action"]["enum"] == [
        "finish",
        "ask_user",
    ]


async def test_observations_are_compacted_to_roughly_120_tokens() -> None:
    agent = _agent()
    observation = agent._compact_observation("長い観測" * 500)
    assert estimate_tokens(observation) <= 120


async def test_history_slice_keeps_latest_eight_messages() -> None:
    history = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"message-{index}"}
        for index in range(10)
    ]
    formatted = RealCampusAgent._format_history(history)
    assert [message["content"] for message in formatted] == [
        f"message-{index}" for index in range(2, 10)
    ]
    assert MAX_HISTORY_MESSAGES == 8


async def test_context_packing_prioritizes_grep_then_high_vector_then_web() -> None:
    grep = _chunk(id="grep", score=1000.0, grep_hit=True, text="grep")
    high = _chunk(id="high", score=0.9, text="high")
    low = _chunk(id="low", score=0.5, text="low")
    web = WebSearchResult("web", "https://example.test/web", "snippet", "web body")
    agent = _agent()

    context = agent._assemble_context_with_budget(
        [low, high, grep],
        [web],
        mode="generate",
        token_budget=None,
    )

    assert context.text.index("text: grep") < context.text.index("text: high")
    assert context.text.index("text: high") < context.text.index("[web:1]")
    assert context.text.index("[web:1]") < context.text.index("text: low")


async def test_generation_budget_keeps_prompt_inside_estimated_window() -> None:
    chunks = [
        _chunk(id=f"chunk-{index}", text="長い根拠" * 500, score=0.9 - index / 100)
        for index in range(5)
    ]
    agent = _agent(llm_context_window=1800, llm_answer_max_tokens=300)
    state = {
        "question": "施設について",
        "history": [{"role": "user", "content": "履歴" * 300}],
        "knowledge_results": chunks,
        "web_results": [],
        "actions_log": [],
    }

    messages, context = agent._build_generation_messages_with_sources(state)

    assert _message_tokens(messages) <= agent._prompt_budget(300)
    assert len(context.knowledge_results) < len(chunks)


async def test_generation_preverify_rebuilds_real_over_budget_prompt() -> None:
    llm = FakeLLMClient(token_counts=[17000, 1000])
    agent = _agent(llm=llm, llm_context_window=16384, llm_answer_max_tokens=1024)
    state = {
        "question": "施設",
        "history": [],
        "knowledge_results": [_chunk(text="根拠" * 2000)],
        "web_results": [],
        "generation_token_budget": 4000,
    }
    messages, context = agent._build_generation_messages_with_sources(state)
    state["generation_messages"] = messages

    result = await agent._verify_generation_prompt(state)

    assert result["generation_token_budget"] < 4000
    assert result["generation_prompt_tokens"] == 1000
    assert isinstance(context, _ContextAssembly)


async def test_generation_retries_context_error_once() -> None:
    llm = RetryLLMClient()
    agent = _agent(llm=llm)
    state = {
        "question": "施設",
        "history": [],
        "knowledge_results": [_chunk()],
        "web_results": [],
        "generation_token_budget": 500,
    }
    messages = agent._build_generation_messages(state)

    tokens = [token async for token in agent._stream_generation_with_retry(state, messages)]

    assert tokens == ["retry ok"]
    assert len(llm.stream_calls) == 2
    assert state["generation_token_budget"] == 250


async def test_sources_are_deduped_and_location_source_is_added() -> None:
    chunk_a = _chunk(id="a")
    chunk_b = _chunk(id="b")
    agent = _agent()
    destination = resolve_location("D404")
    state = {
        "route_destination": destination,
        "knowledge_results": [chunk_a, chunk_b],
        "web_results": [],
    }
    context = _ContextAssembly(
        text="",
        knowledge_results=[chunk_a, chunk_b],
        web_results=[],
    )

    sources = agent._assemble_generation_sources(state, context)

    assert sources == [
        Source(title="食堂", url="https://example.test/facility", type="knowledge"),
        LOCATION_INDEX_SOURCE,
    ]


async def test_web_page_fetch_extracts_main_text() -> None:
    url = "https://example.test/page"
    agent = _agent(
        http_client_factory=_http_factory(
            {url: "<html><nav>除外</nav><main><h1>見出し</h1><p>本文です</p></main></html>"}
        )
    )
    results = await agent._fetch_search_results(
        [WebSearchResult("title", url, "snippet", "")],
        keywords=["本文"],
    )
    assert results[0].text == "見出し 本文です"


async def test_map_free_stream_has_status_then_token_then_done() -> None:
    llm = FakeLLMClient(
        completions=[
            _decision("retrieve", {"queries": ["一般質問"]}),
            _decision("finish", {"reason": "完了"}),
        ],
        tokens=["回答"],
    )
    events = await _collect(_agent(llm=llm), "一般質問")

    names = [event for event, _ in events]
    first_token = names.index("token")
    assert all(name == "status" for name in names[:first_token])
    assert "map" not in names
    assert names[-1] == "done"


async def test_agent_trace_contains_decide_budget_and_navigator_fast_path(
    caplog,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENT_TRACE", "1")
    caplog.set_level(logging.INFO, logger="agent.trace")
    llm = FakeLLMClient(
        completions=[
            _decision("campus_navigator", {"request": "GI512の場所"}),
            _decision("finish", {"reason": "解決"}),
        ],
        tokens=["回答"],
    )

    await _collect(_agent(llm=llm), "GI512はどこ？")

    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "agent.trace"
    ]
    decide = next(record for record in records if record["event"] == "decide")
    navigator = next(
        record for record in records if record["event"] == "campus_navigator"
    )
    assert {"thought", "action", "budget"} <= decide.keys()
    assert navigator["fast_path"] is True


async def test_agent_trace_can_be_disabled(caplog, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_TRACE", "0")
    caplog.set_level(logging.INFO, logger="agent.trace")
    llm = FakeLLMClient(
        completions=[
            _decision("retrieve", {"queries": ["食堂"]}),
            _decision("finish", {"reason": "完了"}),
        ],
        tokens=["回答"],
    )

    await _collect(_agent(llm=llm), "食堂")

    assert [record for record in caplog.records if record.name == "agent.trace"] == []


async def test_generate_system_prompt_contains_deflection_ban_rule() -> None:
    assert "丸投げ" in GENERATE_SYSTEM_PROMPT
    assert "根拠に記載がある場合のみ" in GENERATE_SYSTEM_PROMPT
    assert "直前の会話から引き継いだ" in GENERATE_SYSTEM_PROMPT


async def test_prompt_budget_reserves_answer_and_margin() -> None:
    agent = _agent(llm_context_window=4096, llm_answer_max_tokens=640)
    assert agent._prompt_budget(640) == 4096 - 640 - PROMPT_MARGIN_TOKENS
    assert MIN_GENERATION_CONTEXT_TOKENS == 384
