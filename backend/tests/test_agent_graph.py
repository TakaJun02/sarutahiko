from __future__ import annotations

from pathlib import Path

import pytest
import httpx
from openai import BadRequestError

from app.agent.graph import GENERATE_SYSTEM_PROMPT, PROMPT_MARGIN_TOKENS, RealCampusAgent, estimate_tokens
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

    async def search(self, query: str, *, max_results: int):
        self.calls.append({"query": query, "max_results": max_results})
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
    )


def _http_factory(html_by_url: dict[str, str]):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html_by_url[str(request.url)])

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=8.0)


def _message_tokens(messages: list[dict[str, str]]) -> int:
    return sum(estimate_tokens(message["content"]) for message in messages)


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


async def test_analyze_falls_back_to_raw_question_on_parse_failure() -> None:
    llm = FakeLLMClient(completions=["not json"])
    agent = _agent(llm=llm)

    result = await agent._analyze({"question": "サークルは？", "history": []})

    assert result == {"retrieval_queries": ["サークルは？"], "keywords": []}


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
    assert all(call["limit"] == 6 for call in store.calls)
    assert len(result["knowledge_results"]) == 10
    assert result["knowledge_results"][0].id == "shared"
    assert result["knowledge_results"][0].title == "高いスコア"


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
        "site:akita-pu.ac.jp 秋田県立大学 学長",
        "秋田県立大学 学長 プロフィール",
    ]
    assert events[-2] == ("token", {"text": "最終回答"})
    assert llm.stream_calls[0]["temperature"] == 0.7


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


async def test_context_packing_prioritizes_grep_hits_then_web_then_vector_only_chunks() -> None:
    agent = _agent()
    grep = _chunk(id="grep", score=0.10, text="GREP_CONTEXT", grep_hit=True, grep_keywords=("研究室",))
    vector = _chunk(id="vector", score=0.99, text="VECTOR_CONTEXT")
    web = WebSearchResult("Web", "https://example.test/web", "snippet", "WEB_CONTEXT")

    context = agent._assemble_context_with_budget([vector, grep], [web], mode="generate", token_budget=400)

    assert context.text.index("GREP_CONTEXT") < context.text.index("WEB_CONTEXT")
    assert context.text.index("WEB_CONTEXT") < context.text.index("VECTOR_CONTEXT")
    assert [chunk.id for chunk in context.knowledge_results] == ["grep", "vector"]
    assert [result.url for result in context.web_results] == ["https://example.test/web"]


async def test_generation_budget_drops_history_before_trimming_context() -> None:
    agent = _agent(llm_context_window=1200, llm_answer_max_tokens=200)
    history = [
        {"role": "user", "content": "HISTORY_USER " + ("あ" * 800)},
        {"role": "assistant", "content": "HISTORY_ASSISTANT " + ("い" * 800)},
    ]
    state = {
        "question": "食堂はどこですか？",
        "role": "highschool",
        "history": history,
        "knowledge_results": [
            _chunk(id="high", title="High score", score=0.99, text="HIGH_CONTEXT " + ("う" * 2400))
        ],
        "web_results": [],
    }

    messages = agent._build_generation_messages(state)
    prompt_budget = 1200 - 200 - PROMPT_MARGIN_TOKENS
    combined = "\n".join(message["content"] for message in messages)

    assert _message_tokens(messages) <= prompt_budget
    assert "HISTORY_USER" not in combined
    assert "HISTORY_ASSISTANT" not in combined
    assert "HIGH_CONTEXT" in combined


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
    agent = _agent(llm_context_window=1400)
    state = {
        "question": "施設について教えて",
        "knowledge_results": [_chunk(id="facility", title="施設", text="施設情報 " + ("あ" * 2000), score=0.9)],
        "web_results": [
            WebSearchResult("公式ページ", "https://example.test/facility", "snippet", "WEB_SUMMARY " + ("い" * 2000))
        ],
    }

    messages = agent._build_evaluate_messages(state)
    prompt_budget = 1400 - 300 - PROMPT_MARGIN_TOKENS
    combined = "\n".join(message["content"] for message in messages)

    assert _message_tokens(messages) <= prompt_budget
    assert "summary:" in combined
    assert "WEB_SUMMARY" in combined
    assert "い" * 500 not in combined


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


async def test_give_up_gate_controls_investigation_log() -> None:
    agent = _agent()
    state = {
        "question": "不明な制度は？",
        "role": "highschool",
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
        "used_web_queries": ["site:akita-pu.ac.jp 不明な制度", "不明な制度 秋田県立大学"],
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
    assert system_prompt == GENERATE_SYSTEM_PROMPT
    assert "丸投げする表現を回答の主内容にしない" in system_prompt
    assert "公式サイトでご確認ください" in system_prompt
    assert "学内ナレッジを優先" in system_prompt


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
        token_counts=[1000, 800],
        tokens=["回答"],
    )
    store = FakeKnowledgeStore(
        [_chunk(id="long", title="長い根拠", text="CONTEXT_START " + ("秋田県立大学" * 400), score=0.99)]
    )
    agent = _agent(llm=llm, store=store, llm_context_window=1200, llm_answer_max_tokens=200)

    await _collect(agent, "施設について教えて")

    streamed_prompt = "\n\n".join(message["content"] for message in llm.stream_calls[0]["messages"])
    assert len(llm.count_token_texts) == 2
    assert len(llm.count_token_texts[1]) < len(llm.count_token_texts[0])
    assert streamed_prompt == llm.count_token_texts[1]


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
    agent = _agent(llm=llm, store=store, llm_context_window=1200, llm_answer_max_tokens=200)

    events = await _collect(agent, "施設について教えて")

    first_prompt = "\n\n".join(message["content"] for message in llm.stream_calls[0]["messages"])
    retry_prompt = "\n\n".join(message["content"] for message in llm.stream_calls[1]["messages"])
    assert events[-2] == ("token", {"text": "retry ok"})
    assert len(llm.stream_calls) == 2
    assert len(retry_prompt) < len(first_prompt)
