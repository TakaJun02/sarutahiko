from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from html.parser import HTMLParser
from typing import Any, Literal, TypedDict

import httpx
from langgraph.graph import END, StateGraph
from openai import BadRequestError

from app.models.auth import User
from app.models.chat import DonePayload, Source, StatusPayload, TokenPayload
from app.rag.lexical import generate_keyword_variants, normalize_text, strip_keyword_suffix
from app.rag.models import KnowledgeChunk
from app.search.models import WebSearchResult

Step = Literal["analyze", "retrieve", "search", "web_search", "evaluate", "generate"]

MAX_RETRIEVAL_QUERIES = 3
MAX_ANALYZE_KEYWORDS = 4
MAX_EVALUATE_GREP_KEYWORDS = 3
MAX_EVALUATE_RETRIEVAL_QUERIES = 2
MAX_KNOWLEDGE_CONTEXT_CHUNKS = 10
HIGH_RELEVANCE_CONTEXT_THRESHOLD = 0.60
MAX_LOCAL_SEARCH_FOLLOWUPS = 1
MAX_RETRIEVAL_FOLLOWUPS = 1
MAX_WEB_SEARCH_ROUNDS = 3
MIN_WEB_ROUNDS_BEFORE_GIVE_UP = 2
MAX_WEB_RESULTS_PER_ROUND = 5
MAX_WEB_PAGES_PER_ROUND = 3
# With a 2816-token window one 4000-char page alone exceeds the whole context
# budget, so a single (possibly irrelevant) page crowded out every other
# source. Smaller slices let 2-3 pages coexist — diversity answers more
# questions than depth at this window size.
MAX_WEB_PAGE_CHARS = 1400
ANALYZE_MAX_TOKENS = 300
EVALUATE_MAX_TOKENS = 300
DEFAULT_LLM_CONTEXT_WINDOW = 2816
DEFAULT_LLM_ANSWER_MAX_TOKENS = 640
PROMPT_MARGIN_TOKENS = 192
REAL_TOKEN_HEADROOM = 64
REAL_TOKEN_REBUILD_SCALE = 0.95
CONTEXT_RETRY_SCALE = 0.5
MAX_HISTORY_MESSAGES = 4
MAX_HISTORY_CHARS = 500
MIN_GENERATION_CONTEXT_TOKENS = 384
GENERATION_HISTORY_CHAR_STAGES = (MAX_HISTORY_CHARS, 250, 120)

STATUS_TEXTS: dict[Step, str] = {
    "analyze": "質問の意図を整理しています…",
    "retrieve": "学内ナレッジを検索しています…",
    "search": "学内資料を全文検索しています…",
    "evaluate": "情報が十分か確認しています…",
    "web_search": "Webで最新情報を確認しています…",
    "generate": "回答をまとめています…",
}

FOLLOWUP_STATUS_TEXTS: dict[Step, str] = {
    "retrieve": "観点を変えて学内ナレッジを検索しています…",
    "search": "別のキーワードで学内資料を調べています…",
    "evaluate": "集めた情報を検証しています…",
    "web_search": "別の観点でWebを調べています…",
}

THIRD_WEB_SEARCH_STATUS_TEXT = "さらに手掛かりを探しています…"
OFFICIAL_SEARCH_DOMAIN = "akita-pu.ac.jp"

logger = logging.getLogger(__name__)

GENERATE_SYSTEM_PROMPT = """あなたは秋田県立大学 本荘キャンパスのオープンキャンパス2026来場者向け案内AIです。
回答は日本語で、丁寧でフレンドリーな文体にしてください。
利用者ロール別のトーンは次を守ってください。highschool: 高校生にも分かりやすい語彙で、親しみやすく丁寧に答える。parent: 保護者が確認しやすいように、要点と注意点を整理して答える。other: 来場者に向けて、必要な情報を簡潔かつ丁寧に答える。

回答ルール:
1. 禁止: 「公式サイトでご確認ください」「当日の学科紹介でご確認いただけます」など、調べれば答えられる内容を利用者に丸投げする表現を回答の主内容にしないでください。
2. コンテキストにある情報は、数字・固有名詞・手順まで具体的に盛り込み、省略しないでください。
3. 検索を尽くしても根拠がない場合のみ「現時点で確認できなかった」と正直に述べ、何をどこまで調べたか（学内ナレッジ・大学公式サイトのWeb検索）を一言添えてください。その場合に限り、補助情報として問い合わせ先を案内して構いません。
4. 年度依存情報は年度を明記し、根拠にない内容やURLを捏造しないでください。
5. 学内ナレッジは大学公式サイトの最新転記です。Web検索結果と学内ナレッジが矛盾する場合は学内ナレッジを優先し、Webの古いページ（過去の役職者・旧年度情報など）に引きずられないでください。"""


def estimate_tokens(text: str) -> int:
    # Japanese-heavy prompts are estimated with a character heuristic.
    # A measured production prompt was 3573 chars = 2565 real Gemma tokens
    # (0.718 tokens/char), so 0.75 keeps safety margin for kanji-dense text.
    return max((len(text) * 3) // 4, 1)


class AgentState(TypedDict, total=False):
    question: str
    role: str
    history: list[dict]
    retrieval_queries: list[str]
    keywords: list[str]
    knowledge_results: list[KnowledgeChunk]
    web_results: list[WebSearchResult]
    sufficient: bool
    missing: str
    grep_keywords: list[str]
    followup_retrieval_queries: list[str]
    web_queries: list[str]
    web_search_rounds: int
    local_search_followups: int
    retrieval_followups: int
    retrieval_rounds: int
    search_rounds: int
    retrieve_executed: bool
    search_executed: bool
    search_variant_executed: bool
    search_terms: list[str]
    search_variant_terms: list[str]
    search_hit_count: int
    used_web_queries: list[str]
    used_web_query_keys: list[str]
    used_retrieval_queries: list[str]
    generation_messages: list[dict[str, str]]
    generation_token_budget: int
    sources: list[Source]


class _FallbackTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "nav"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "nav"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data)

    @property
    def text(self) -> str:
        return " ".join(" ".join(self._parts).split())


@dataclass(frozen=True)
class _ContextAssembly:
    text: str
    knowledge_results: list[KnowledgeChunk]
    web_results: list[WebSearchResult]


@dataclass(frozen=True)
class _WebRoundOutcome:
    candidates: list[WebSearchResult]
    executed_queries: list[str]
    executed_query_keys: list[str]


@dataclass(frozen=True)
class _WebExecutionOutcome:
    results: list[WebSearchResult]
    raw_result_count: int


class RealCampusAgent:
    def __init__(
        self,
        *,
        llm_client: Any,
        knowledge_store: Any,
        search_provider: Any,
        lexical_search: Any | None = None,
        top_k: int = 6,
        min_relevance_score: float = 0.45,
        http_client_factory: Callable[[], Any] | None = None,
        llm_context_window: int = DEFAULT_LLM_CONTEXT_WINDOW,
        llm_answer_max_tokens: int = DEFAULT_LLM_ANSWER_MAX_TOKENS,
    ) -> None:
        self.llm_client = llm_client
        self.knowledge_store = knowledge_store
        self.lexical_search = lexical_search
        self.search_provider = search_provider
        self.top_k = top_k
        self.min_relevance_score = min_relevance_score
        self.http_client_factory = http_client_factory or self._default_http_client
        self.llm_context_window = llm_context_window
        self.llm_answer_max_tokens = llm_answer_max_tokens
        self._graph = self._build_graph()

    async def stream(
        self,
        question: str,
        user: User,
        thread_id: str,
        message_id: str,
        history: list[dict] | None = None,
    ) -> AsyncIterator[tuple[str, dict]]:
        state: AgentState = {
            "question": question.strip(),
            "role": user.role,
            "history": (history or [])[-MAX_HISTORY_MESSAGES:],
            "knowledge_results": [],
            "web_results": [],
            "web_search_rounds": 0,
            "local_search_followups": 0,
            "retrieval_followups": 0,
            "retrieval_rounds": 0,
            "search_rounds": 0,
            "retrieve_executed": False,
            "search_executed": False,
            "search_variant_executed": False,
            "search_terms": [],
            "search_variant_terms": [],
            "search_hit_count": 0,
            "used_web_queries": [],
            "used_web_query_keys": [],
            "used_retrieval_queries": [],
        }

        yield "status", self._status("analyze", state)
        state.update(await self._analyze(state))

        yield "status", self._status("retrieve", state)
        try:
            state.update(await self._retrieve(state))
        except Exception as exc:
            logger.warning("Retrieve step failed: %s", exc.__class__.__name__)
            state.update(
                {
                    "retrieve_executed": True,
                    "retrieval_rounds": state.get("retrieval_rounds", 0) + 1,
                }
            )

        yield "status", self._status("search", state)
        try:
            state.update(await self._search(state))
        except Exception as exc:
            logger.warning("Search step failed: %s", exc.__class__.__name__)
            state.update(
                {
                    "search_rounds": state.get("search_rounds", 0) + 1,
                    "search_executed": True,
                }
            )

        yield "status", self._status("evaluate", state)
        state.update(await self._evaluate(state))

        while True:
            route = self._route_after_evaluate(state)
            if route == "search":
                state["local_search_followups"] = state.get("local_search_followups", 0) + 1
                yield "status", self._status("search", state)
                try:
                    state.update(await self._search(state, keywords=state.get("grep_keywords") or []))
                except Exception as exc:
                    logger.warning("Search follow-up step failed: %s", exc.__class__.__name__)
                    state.update(
                        {
                            "search_rounds": state.get("search_rounds", 0) + 1,
                            "search_executed": True,
                        }
                    )

                yield "status", self._status("evaluate", state)
                state.update(await self._evaluate(state))
                continue

            if route == "retrieve":
                state["retrieval_followups"] = state.get("retrieval_followups", 0) + 1
                yield "status", self._status("retrieve", state)
                try:
                    state.update(await self._retrieve(state))
                except Exception as exc:
                    logger.warning("Retrieve follow-up step failed: %s", exc.__class__.__name__)
                    state.update(
                        {
                            "retrieve_executed": True,
                            "retrieval_rounds": state.get("retrieval_rounds", 0) + 1,
                        }
                    )

                yield "status", self._status("evaluate", state)
                state.update(await self._evaluate(state))
                continue

            if route == "web_search":
                yield "status", self._status("web_search", state)
                try:
                    state.update(await self._web_search(state))
                except Exception as exc:
                    logger.warning("Web search step failed: %s", exc.__class__.__name__)
                    state.update({"web_search_rounds": state.get("web_search_rounds", 0) + 1})

                yield "status", self._status("evaluate", state)
                state.update(await self._evaluate(state))
                continue

            break

        yield "status", self._status("generate", state)
        state.update(await self._prepare_generation(state))
        state.update(await self._verify_generation_prompt(state))

        messages = state.get("generation_messages") or self._build_generation_messages(state)
        async for token in self._stream_generation_with_retry(state, messages):
            yield "token", TokenPayload(text=token).model_dump()

        yield "done", DonePayload(
            thread_id=thread_id,
            message_id=message_id,
            sources=state.get("sources", []),
        ).model_dump()

    @staticmethod
    def format_sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"

    def _build_graph(self) -> Any:
        workflow = StateGraph(AgentState)
        workflow.add_node("analyze", self._analyze)
        workflow.add_node("retrieve", self._retrieve)
        workflow.add_node("retrieve_followup", self._retrieve)
        workflow.add_node("search", self._search)
        workflow.add_node("evaluate", self._evaluate)
        workflow.add_node("web_search", self._web_search)
        workflow.add_node("evaluate_after_web", self._evaluate_after_web)
        workflow.add_node("web_search_second", self._web_search_second)
        workflow.add_node("evaluate_after_second", self._evaluate_after_second)
        workflow.add_node("generate", self._prepare_generation)
        workflow.set_entry_point("analyze")
        workflow.add_edge("analyze", "retrieve")
        workflow.add_edge("retrieve", "search")
        workflow.add_edge("search", "evaluate")
        workflow.add_conditional_edges(
            "evaluate",
            self._route_after_evaluate,
            {
                "search": "search",
                "retrieve": "retrieve_followup",
                "web_search": "web_search",
                "generate": "generate",
            },
        )
        workflow.add_edge("retrieve_followup", "evaluate")
        workflow.add_edge("web_search", "evaluate_after_web")
        workflow.add_conditional_edges(
            "evaluate_after_web",
            self._route_after_first_web_evaluate,
            {
                "web_search_second": "web_search_second",
                "generate": "generate",
            },
        )
        workflow.add_edge("web_search_second", "evaluate_after_second")
        workflow.add_edge("evaluate_after_second", "generate")
        workflow.add_edge("generate", END)
        return workflow.compile()

    async def _analyze(self, state: AgentState) -> dict:
        question = state["question"]
        raw_output = await self.llm_client.complete_chat(
            self._build_analyze_messages(question, state.get("history", [])),
            temperature=0.2,
            max_tokens=ANALYZE_MAX_TOKENS,
            enable_thinking=False,
        )
        payload = self._parse_json_object(raw_output)
        queries = self._normalize_queries(
            payload.get("retrieval_queries") if payload else None,
            fallback=[question],
            limit=MAX_RETRIEVAL_QUERIES,
        )
        keywords = self._normalize_queries(
            payload.get("keywords") if payload else None,
            fallback=[],
            limit=MAX_ANALYZE_KEYWORDS,
        )
        return {"retrieval_queries": queries, "keywords": keywords}

    async def _retrieve(self, state: AgentState, queries: Sequence[str] | None = None) -> dict:
        existing_results = state.get("knowledge_results") or []
        retrieved_results: list[KnowledgeChunk] = []
        active_queries = self._unused_retrieval_queries(
            state,
            self._retrieval_queries_for_round(state, queries),
        )
        used_query_keys = list(state.get("used_retrieval_queries") or [])

        for query in active_queries:
            used_query_keys.append(self._retrieval_query_key(query))
            results = await self.knowledge_store.search(query, limit=self.top_k)
            for chunk in results:
                if self._is_below_relevance_floor(chunk):
                    continue
                retrieved_results.append(chunk)

        merged = self._merge_knowledge_results(existing_results, retrieved_results)
        return {
            "knowledge_results": merged[:MAX_KNOWLEDGE_CONTEXT_CHUNKS],
            "retrieve_executed": True,
            "retrieval_rounds": state.get("retrieval_rounds", 0) + 1,
            "used_retrieval_queries": self._dedupe_keys(used_query_keys),
        }

    async def _search(self, state: AgentState, keywords: Sequence[str] | None = None) -> dict:
        search_keywords = self._search_keywords(state, keywords)
        existing_results = state.get("knowledge_results") or []
        if self.lexical_search is None:
            return {
                "knowledge_results": existing_results,
                "search_rounds": state.get("search_rounds", 0) + 1,
                "search_executed": True,
                "search_terms": self._merge_strings(state.get("search_terms") or [], search_keywords),
                "search_hit_count": state.get("search_hit_count", 0),
            }

        outcome = self.lexical_search.grep_sections_with_trace(search_keywords)
        grep_chunks = [hit.chunk for hit in outcome.hits]
        merged = self._merge_knowledge_results(existing_results, grep_chunks)
        return {
            "knowledge_results": merged[:MAX_KNOWLEDGE_CONTEXT_CHUNKS],
            "search_rounds": state.get("search_rounds", 0) + 1,
            "search_executed": True,
            "search_variant_executed": bool(state.get("search_variant_executed")) or outcome.variants_attempted,
            "search_terms": self._merge_strings(state.get("search_terms") or [], outcome.searched_keywords),
            "search_variant_terms": self._merge_strings(
                state.get("search_variant_terms") or [],
                outcome.variant_keywords,
            ),
            "search_hit_count": state.get("search_hit_count", 0) + len(outcome.hits),
        }

    async def _evaluate(self, state: AgentState) -> dict:
        raw_output = await self.llm_client.complete_chat(
            self._build_evaluate_messages(state),
            temperature=0.2,
            max_tokens=EVALUATE_MAX_TOKENS,
            enable_thinking=False,
        )
        payload = self._parse_json_object(raw_output)
        if payload is None:
            return {
                "sufficient": True,
                "missing": "",
                "grep_keywords": [],
                "followup_retrieval_queries": [],
                "web_queries": [],
            }

        sufficient = self._parse_bool(payload.get("sufficient"), default=True)
        grep_keywords = self._normalize_queries(
            payload.get("grep_keywords"),
            fallback=[],
            limit=MAX_EVALUATE_GREP_KEYWORDS,
        )
        web_queries = self._normalize_queries(
            payload.get("web_queries"),
            fallback=[state["question"]] if not sufficient else [],
            limit=MAX_RETRIEVAL_QUERIES,
        )
        followup_retrieval_queries = self._normalize_queries(
            payload.get("retrieval_queries"),
            fallback=[],
            limit=MAX_EVALUATE_RETRIEVAL_QUERIES,
        )
        return {
            "sufficient": sufficient,
            "missing": str(payload.get("missing") or ""),
            "grep_keywords": grep_keywords,
            "followup_retrieval_queries": followup_retrieval_queries,
            "web_queries": web_queries,
        }

    async def _evaluate_after_web(self, state: AgentState) -> dict:
        return await self._evaluate(state)

    async def _evaluate_after_second(self, state: AgentState) -> dict:
        return await self._evaluate(state)

    async def _web_search(self, state: AgentState) -> dict:
        round_number = state.get("web_search_rounds", 0) + 1
        outcome = await self._search_web_round(
            state=state,
            round_number=round_number,
            existing_urls={result.url for result in state.get("web_results", [])},
        )
        prioritized = self._prioritize_search_results(outcome.candidates, self._web_focus_keywords(state))
        fetched_results = await self._fetch_search_results(
            prioritized[:MAX_WEB_PAGES_PER_ROUND],
            keywords=self._web_focus_keywords(state),
        )
        web_results = self._dedupe_web_results([*(state.get("web_results") or []), *fetched_results])
        return {
            "web_results": web_results,
            "web_search_rounds": round_number,
            "used_web_queries": self._merge_strings(state.get("used_web_queries") or [], outcome.executed_queries),
            "used_web_query_keys": self._dedupe_keys(
                [*(state.get("used_web_query_keys") or []), *outcome.executed_query_keys]
            ),
        }

    async def _web_search_second(self, state: AgentState) -> dict:
        return await self._web_search(state)

    async def _prepare_generation(self, state: AgentState) -> dict:
        messages, context = self._build_generation_messages_with_sources(state)
        sources = self._assemble_sources(context.knowledge_results, context.web_results)
        return {
            "generation_messages": messages,
            "generation_token_budget": estimate_tokens(context.text),
            "sources": sources,
        }

    async def _verify_generation_prompt(self, state: AgentState) -> dict:
        messages = state.get("generation_messages") or self._build_generation_messages(state)
        count = await self._count_real_tokens(messages)
        if count is None or not self._exceeds_generation_context(count):
            return {}

        available_prompt_tokens = self._available_generation_prompt_tokens()
        factor = (available_prompt_tokens / count) * REAL_TOKEN_REBUILD_SCALE if count > 0 else 0
        current_budget = int(state.get("generation_token_budget", 0))
        reduced_budget = max(int(current_budget * factor), 0)
        messages, context = self._build_generation_messages_with_sources(state, token_budget=reduced_budget)
        sources = self._assemble_sources(context.knowledge_results, context.web_results)
        await self._count_real_tokens(messages)
        return {
            "generation_messages": messages,
            "generation_token_budget": reduced_budget,
            "sources": sources,
        }

    async def _stream_generation_with_retry(
        self,
        state: AgentState,
        messages: Sequence[dict[str, str]],
    ) -> AsyncIterator[str]:
        try:
            async for token in self.llm_client.stream_chat(
                messages,
                temperature=0.7,
                max_tokens=self.llm_answer_max_tokens,
                enable_thinking=False,
            ):
                yield token
        except BadRequestError as exc:
            if not self._is_context_length_exceeded(exc):
                raise
            retry_budget = max(int(state.get("generation_token_budget", 0) * CONTEXT_RETRY_SCALE), 0)
            retry_messages, retry_context = self._build_generation_messages_with_sources(
                state,
                token_budget=retry_budget,
            )
            state["generation_messages"] = retry_messages
            state["generation_token_budget"] = retry_budget
            state["sources"] = self._assemble_sources(retry_context.knowledge_results, retry_context.web_results)
            async for token in self.llm_client.stream_chat(
                retry_messages,
                temperature=0.7,
                max_tokens=self.llm_answer_max_tokens,
                enable_thinking=False,
            ):
                yield token

    def _route_after_evaluate(self, state: AgentState) -> str:
        if state.get("sufficient", True):
            return "generate"
        if (
            state.get("grep_keywords")
            and state.get("local_search_followups", 0) < MAX_LOCAL_SEARCH_FOLLOWUPS
        ):
            return "search"
        if (
            state.get("followup_retrieval_queries")
            and state.get("retrieval_followups", 0) < MAX_RETRIEVAL_FOLLOWUPS
            and self._has_unused_retrieval_queries(state)
        ):
            return "retrieve"
        if self._should_run_web_search(state):
            return "web_search"
        return "generate"

    def _route_after_first_web_evaluate(self, state: AgentState) -> str:
        if self._route_after_evaluate(state) == "web_search":
            return "web_search_second"
        return "generate"

    def _next_step_after(self, node_name: str, state: AgentState) -> Step | None:
        if node_name == "analyze":
            return "retrieve"
        if node_name == "retrieve":
            return "search"
        if node_name == "search":
            return "evaluate"
        if node_name == "evaluate":
            route = self._route_after_evaluate(state)
            return route if route in {"search", "retrieve", "web_search"} else "generate"
        if node_name == "retrieve_followup":
            return "evaluate"
        if node_name == "web_search":
            return "evaluate"
        if node_name == "evaluate_after_web":
            return "web_search" if self._route_after_first_web_evaluate(state) == "web_search_second" else "generate"
        if node_name == "web_search_second":
            return "evaluate"
        if node_name == "evaluate_after_second":
            return "generate"
        return None

    @staticmethod
    def _status(step: Step, state: AgentState | None = None) -> dict:
        current_state = state or {}
        if step == "web_search" and current_state.get("web_search_rounds", 0) >= 2:
            text = THIRD_WEB_SEARCH_STATUS_TEXT
        elif step == "retrieve" and current_state.get("retrieve_executed"):
            text = FOLLOWUP_STATUS_TEXTS["retrieve"]
        elif step == "search" and current_state.get("search_rounds", 0) >= 1:
            text = FOLLOWUP_STATUS_TEXTS["search"]
        else:
            web_rounds = current_state.get("web_search_rounds", 0)
            text = FOLLOWUP_STATUS_TEXTS.get(step, STATUS_TEXTS[step]) if web_rounds >= 1 else STATUS_TEXTS[step]
        return StatusPayload(step=step, text=text).model_dump()

    def _build_analyze_messages(self, question: str, history: Sequence[dict]) -> list[dict[str, str]]:
        messages = self._raw_analyze_messages(question, self._format_history(history))
        if self._fits_prompt_budget(messages, ANALYZE_MAX_TOKENS):
            return messages
        return self._truncate_last_user_message(messages, ANALYZE_MAX_TOKENS)

    @staticmethod
    def _raw_analyze_messages(question: str, history_messages: Sequence[dict[str, str]]) -> list[dict[str, str]]:
        messages = [
            {
                "role": "system",
                "content": (
                    "あなたは秋田県立大学 本荘キャンパス案内AIの検索計画担当です。"
                    "質問と直近履歴から、学内ナレッジ検索に使う観点違いの検索クエリを2〜3本作ってください。"
                    "質問中の固有名詞・専門用語・レアな語（研究室名・人名・制度名・建物名など）を言い換えず最大4語 keywords に入れてください。"
                    "一般語（先生、場所、方法など）は keywords に含めないでください。"
                    "出力はJSONのみで、形式は {\"retrieval_queries\": [\"...\", \"...\"], \"keywords\": [\"...\"], \"intent\": \"...\"} です。"
                ),
            },
        ]
        messages.extend(history_messages)
        messages.append({"role": "user", "content": f"質問:\n{question}"})
        return messages

    def _build_evaluate_messages(self, state: AgentState) -> list[dict[str, str]]:
        messages, _ = self._build_budgeted_context_messages(
            system_content=(
                "あなたは秋田県立大学 本荘キャンパス案内AIの根拠評価担当です。"
                "来場者に具体的な回答（数字・固有名詞・手順）を返せるかを判定してください。"
                "一般論しか言えない、重要な詳細が欠ける、根拠が曖昧な場合は insufficient としてください。"
                "質問が特定の値（人名・数値・日時・場所・URL）を尋ねている場合、その値そのものがコンテキストに含まれていなければ、関連説明があっても必ず insufficient としてください。"
                "出力はJSONのみで、形式は {\"sufficient\": true|false, \"missing\": \"...\", \"grep_keywords\": [\"...\"], \"retrieval_queries\": [\"...\", \"...\"], \"web_queries\": [\"...\", \"...\"]} です。"
                "不足時、学内資料を全文検索すれば埋まりそうな固有名詞があれば grep_keywords に最大3語で返してください。"
                "不足時、ベクトル検索の観点を変えれば埋まりそうなら retrieval_queries に既出と別観点の短いクエリを最大2件で返してください。"
                "不足時のweb_queriesは、追加Web検索で使う短い日本語クエリにしてください。"
                "web_queries は前回までと違う観点にしてください。"
            ),
            user_content_factory=lambda context: (
                f"質問: {state['question']}\n\n"
                f"現在のコンテキスト:\n{context}\n\n"
                f"{self._format_search_note(state)}"
            ),
            knowledge_results=state.get("knowledge_results") or [],
            web_results=state.get("web_results") or [],
            max_tokens=EVALUATE_MAX_TOKENS,
            context_mode="evaluate",
        )
        return messages

    def _build_generation_messages(self, state: AgentState) -> list[dict[str, str]]:
        messages, _ = self._build_generation_messages_with_sources(state)
        return messages

    def _build_generation_messages_with_sources(
        self,
        state: AgentState,
        *,
        token_budget: int | None = None,
    ) -> tuple[list[dict[str, str]], _ContextAssembly]:
        user_content_factory = lambda context: (
                f"利用者ロール: {state.get('role', 'other')}\n"
                f"現在日付: {date.today().isoformat()}\n"
                f"質問: {state['question']}\n\n"
                "利用可能な根拠:\n"
                f"{context}\n\n"
                f"{self._generation_investigation_log_line(state)}"
                "上の根拠だけに基づいて回答してください。"
        )
        history_messages, context_budget = self._generation_history_and_context_budget(
            state.get("history", []),
            GENERATE_SYSTEM_PROMPT,
            user_content_factory,
            self.llm_answer_max_tokens,
            requested_context_budget=token_budget,
        )

        if token_budget is None:
            full_context = self._assemble_context_with_budget(
                state.get("knowledge_results") or [],
                state.get("web_results") or [],
                mode="generate",
                token_budget=None,
            )
            messages = self._compose_context_messages(
                GENERATE_SYSTEM_PROMPT,
                history_messages,
                user_content_factory,
                full_context.text,
            )
            if self._fits_prompt_budget(messages, self.llm_answer_max_tokens):
                return messages, full_context

        return self._build_messages_with_context_budget(
            system_content=GENERATE_SYSTEM_PROMPT,
            user_content_factory=user_content_factory,
            knowledge_results=state.get("knowledge_results") or [],
            web_results=state.get("web_results") or [],
            max_tokens=self.llm_answer_max_tokens,
            context_mode="generate",
            history_messages=history_messages,
            context_token_budget=context_budget,
        )

    def _generation_history_and_context_budget(
        self,
        raw_history: Sequence[dict],
        system_content: str,
        user_content_factory: Callable[[str], str],
        max_tokens: int,
        *,
        requested_context_budget: int | None,
    ) -> tuple[list[dict[str, str]], int]:
        selected_history: list[dict[str, str]] = []
        selected_budget = 0
        baseline_remaining_budget: int | None = None
        for char_limit in GENERATION_HISTORY_CHAR_STAGES:
            history_messages = self._format_history(raw_history, max_chars=char_limit)
            remaining_budget = self._remaining_context_budget(
                system_content,
                history_messages,
                user_content_factory,
                max_tokens,
            )
            if baseline_remaining_budget is None:
                baseline_remaining_budget = remaining_budget
            context_budget = self._generation_context_budget(
                remaining_budget,
                requested_context_budget=requested_context_budget,
                freed_history_tokens=max(remaining_budget - baseline_remaining_budget, 0),
            )
            selected_history = history_messages
            selected_budget = context_budget
            if context_budget >= MIN_GENERATION_CONTEXT_TOKENS:
                break
        return selected_history, selected_budget

    @staticmethod
    def _generation_context_budget(
        remaining_budget: int,
        *,
        requested_context_budget: int | None,
        freed_history_tokens: int = 0,
    ) -> int:
        if requested_context_budget is None:
            return remaining_budget
        requested_budget = max(requested_context_budget, 0) + max(freed_history_tokens, 0)
        return min(remaining_budget, requested_budget)

    def _build_budgeted_context_messages(
        self,
        *,
        system_content: str,
        user_content_factory: Callable[[str], str],
        knowledge_results: Sequence[KnowledgeChunk],
        web_results: Sequence[WebSearchResult],
        max_tokens: int,
        context_mode: Literal["evaluate", "generate"],
        history_messages: Sequence[dict[str, str]] | None = None,
        context_token_budget: int | None = None,
    ) -> tuple[list[dict[str, str]], _ContextAssembly]:
        active_history = list(history_messages or [])
        if context_token_budget is not None:
            return self._build_messages_with_forced_context_budget(
                system_content=system_content,
                user_content_factory=user_content_factory,
                knowledge_results=knowledge_results,
                web_results=web_results,
                max_tokens=max_tokens,
                context_mode=context_mode,
                history_messages=active_history,
                context_token_budget=context_token_budget,
            )
        full_context = self._assemble_context_with_budget(
            knowledge_results,
            web_results,
            mode=context_mode,
            token_budget=None,
        )
        messages = self._compose_context_messages(system_content, active_history, user_content_factory, full_context.text)
        if self._fits_prompt_budget(messages, max_tokens):
            return messages, full_context

        context_budget = self._remaining_context_budget(
            system_content,
            active_history,
            user_content_factory,
            max_tokens,
        )
        return self._build_messages_with_context_budget(
            system_content=system_content,
            user_content_factory=user_content_factory,
            knowledge_results=knowledge_results,
            web_results=web_results,
            max_tokens=max_tokens,
            context_mode=context_mode,
            history_messages=active_history,
            context_token_budget=context_budget,
        )

    def _build_messages_with_forced_context_budget(
        self,
        *,
        system_content: str,
        user_content_factory: Callable[[str], str],
        knowledge_results: Sequence[KnowledgeChunk],
        web_results: Sequence[WebSearchResult],
        max_tokens: int,
        context_mode: Literal["evaluate", "generate"],
        history_messages: Sequence[dict[str, str]],
        context_token_budget: int,
    ) -> tuple[list[dict[str, str]], _ContextAssembly]:
        context_budget = min(
            max(context_token_budget, 0),
            self._remaining_context_budget(
                system_content,
                history_messages,
                user_content_factory,
                max_tokens,
            ),
        )
        return self._build_messages_with_context_budget(
            system_content=system_content,
            user_content_factory=user_content_factory,
            knowledge_results=knowledge_results,
            web_results=web_results,
            max_tokens=max_tokens,
            context_mode=context_mode,
            history_messages=history_messages,
            context_token_budget=context_budget,
        )

    def _remaining_context_budget(
        self,
        system_content: str,
        history_messages: Sequence[dict[str, str]],
        user_content_factory: Callable[[str], str],
        max_tokens: int,
    ) -> int:
        base_messages = self._compose_context_messages(system_content, history_messages, user_content_factory, "")
        return max(self._prompt_budget(max_tokens) - self._estimate_messages(base_messages), 0)

    def _build_messages_with_context_budget(
        self,
        *,
        system_content: str,
        user_content_factory: Callable[[str], str],
        knowledge_results: Sequence[KnowledgeChunk],
        web_results: Sequence[WebSearchResult],
        max_tokens: int,
        context_mode: Literal["evaluate", "generate"],
        history_messages: Sequence[dict[str, str]],
        context_token_budget: int,
    ) -> tuple[list[dict[str, str]], _ContextAssembly]:
        context = self._assemble_context_with_budget(
            knowledge_results,
            web_results,
            mode=context_mode,
            token_budget=context_token_budget,
        )
        messages = self._compose_context_messages(system_content, history_messages, user_content_factory, context.text)
        if self._fits_prompt_budget(messages, max_tokens):
            return messages, context

        best_messages: list[dict[str, str]] | None = None
        best_context: _ContextAssembly | None = None
        low = 0
        high = max(context_token_budget - 1, 0)
        while low <= high:
            candidate_budget = (low + high) // 2
            candidate_context = self._assemble_context_with_budget(
                knowledge_results,
                web_results,
                mode=context_mode,
                token_budget=candidate_budget,
            )
            candidate_messages = self._compose_context_messages(
                system_content,
                history_messages,
                user_content_factory,
                candidate_context.text,
            )
            if self._fits_prompt_budget(candidate_messages, max_tokens):
                best_messages = candidate_messages
                best_context = candidate_context
                low = candidate_budget + 1
            else:
                high = candidate_budget - 1

        if best_messages is not None and best_context is not None:
            return best_messages, best_context
        empty_context = self._assemble_context_with_budget(
            knowledge_results,
            web_results,
            mode=context_mode,
            token_budget=0,
        )
        empty_messages = self._compose_context_messages(
            system_content,
            history_messages,
            user_content_factory,
            empty_context.text,
        )
        return self._truncate_last_user_message(empty_messages, max_tokens), empty_context

    @staticmethod
    def _compose_context_messages(
        system_content: str,
        history_messages: Sequence[dict[str, str]],
        user_content_factory: Callable[[str], str],
        context: str,
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
        messages.extend(history_messages)
        messages.append({"role": "user", "content": user_content_factory(context)})
        return messages

    @staticmethod
    def _format_history(
        history: Sequence[dict],
        *,
        max_chars: int = MAX_HISTORY_CHARS,
    ) -> list[dict[str, str]]:
        formatted: list[dict[str, str]] = []
        for message in history[-MAX_HISTORY_MESSAGES:]:
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = str(message.get("content", "")).strip()
            if content:
                formatted.append({"role": role, "content": content[:max_chars]})
        return formatted

    @staticmethod
    def _format_history_for_prompt(history: Sequence[dict]) -> str:
        lines: list[str] = []
        for message in history[-MAX_HISTORY_MESSAGES:]:
            role = message.get("role")
            content = str(message.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                lines.append(f"{role}: {content[:MAX_HISTORY_CHARS]}")
        return "\n".join(lines) if lines else "なし"

    def _assemble_context_with_budget(
        self,
        knowledge_results: Sequence[KnowledgeChunk],
        web_results: Sequence[WebSearchResult],
        *,
        mode: Literal["evaluate", "generate"],
        token_budget: int | None,
    ) -> _ContextAssembly:
        parts: list[str] = []
        included_knowledge: list[KnowledgeChunk] = []
        included_web: list[WebSearchResult] = []

        def add_knowledge(chunks: Sequence[KnowledgeChunk], *, start_index: int) -> int:
            included_count = 0
            for offset, chunk in enumerate(self._ordered_knowledge_results(chunks), start=start_index):
                added = self._append_context_item(
                    parts,
                    lambda available_tokens, chunk=chunk, index=offset: self._fit_knowledge_context_item(
                        chunk,
                        index,
                        mode=mode,
                        available_tokens=available_tokens,
                    ),
                    token_budget=token_budget,
                )
                if added:
                    included_knowledge.append(chunk)
                    included_count += 1
            return included_count

        def add_web() -> None:
            for index, result in enumerate(web_results, start=1):
                added = self._append_context_item(
                    parts,
                    lambda available_tokens, result=result, index=index: self._fit_web_context_item(
                        result,
                        index,
                        mode=mode,
                        available_tokens=available_tokens,
                    ),
                    token_budget=token_budget,
                )
                if added:
                    included_web.append(result)

        grep_chunks = [chunk for chunk in knowledge_results if chunk.grep_hit]
        vector_chunks = [chunk for chunk in knowledge_results if not chunk.grep_hit]
        high_relevance_vector_chunks = [
            chunk
            for chunk in vector_chunks
            if chunk.score is not None and chunk.score >= HIGH_RELEVANCE_CONTEXT_THRESHOLD
        ]
        remaining_vector_chunks = [
            chunk
            for chunk in vector_chunks
            if chunk.score is None or chunk.score < HIGH_RELEVANCE_CONTEXT_THRESHOLD
        ]
        next_index = add_knowledge(grep_chunks, start_index=1) + 1
        next_index += add_knowledge(high_relevance_vector_chunks, start_index=next_index)
        add_web()
        add_knowledge(remaining_vector_chunks, start_index=next_index)

        return _ContextAssembly(
            text="\n\n".join(parts),
            knowledge_results=included_knowledge,
            web_results=included_web,
        )

    def _append_context_item(
        self,
        parts: list[str],
        build_item: Callable[[int | None], str | None],
        *,
        token_budget: int | None,
    ) -> bool:
        if token_budget is None:
            item = build_item(None)
            if item:
                parts.append(item)
                return True
            return False

        prefix = "\n\n".join(parts)
        separator = "\n\n" if parts else ""
        prefix_tokens = estimate_tokens(f"{prefix}{separator}") if prefix else 0
        available_tokens = token_budget - prefix_tokens
        while available_tokens > 0:
            item = build_item(available_tokens)
            if not item:
                return False
            candidate = f"{prefix}{separator}{item}" if prefix else item
            if estimate_tokens(candidate) <= token_budget:
                parts.append(item)
                return True
            available_tokens -= 1
        return False

    def _fit_knowledge_context_item(
        self,
        chunk: KnowledgeChunk,
        index: int,
        *,
        mode: Literal["evaluate", "generate"],
        available_tokens: int | None,
    ) -> str | None:
        source_urls = ", ".join(chunk.source_urls)
        body = chunk.text.strip()
        body_label = "text"
        if mode == "evaluate":
            if chunk.grep_hit:
                body = self._center_excerpt_on_keywords(body, chunk.grep_keywords, limit=400)
            else:
                body = body[:400]
            body_label = "summary"
        metadata_lines = [
            f"[knowledge:{index}] {chunk.title}",
            f"category: {chunk.category}",
            f"confidence: {chunk.confidence}",
        ]
        if chunk.grep_hit:
            metadata_lines.append("grep_hit: true")
        metadata_lines.extend(
            [
                f"score: {chunk.score}",
                f"source_urls: {source_urls}",
            ]
        )
        return self._fit_context_item(
            metadata_lines,
            body_label=body_label,
            body=body,
            available_tokens=available_tokens,
        )

    def _fit_web_context_item(
        self,
        result: WebSearchResult,
        index: int,
        *,
        mode: Literal["evaluate", "generate"],
        available_tokens: int | None,
    ) -> str | None:
        body = (result.text or result.snippet).strip()
        body_label = "text"
        if mode == "evaluate":
            body = body[:400]
            body_label = "summary"
        return self._fit_context_item(
            [
                f"[web:{index}] {result.title}",
                f"url: {result.url}",
                f"snippet: {result.snippet[:400]}",
            ],
            body_label=body_label,
            body=body,
            available_tokens=available_tokens,
        )

    def _fit_context_item(
        self,
        metadata_lines: Sequence[str],
        *,
        body_label: str,
        body: str,
        available_tokens: int | None,
    ) -> str | None:
        prefix = "\n".join([*metadata_lines, f"{body_label}: "])
        if available_tokens is None:
            return f"{prefix}{body}".rstrip()

        prefix_tokens = estimate_tokens(prefix)
        if prefix_tokens > available_tokens:
            return None

        remaining_tokens = available_tokens - prefix_tokens
        if body and remaining_tokens <= 0:
            return None

        truncated_body = self._truncate_text_to_token_budget(body, remaining_tokens)
        if body and not truncated_body:
            return None

        item = f"{prefix}{truncated_body}".rstrip()
        while estimate_tokens(item) > available_tokens and truncated_body:
            truncated_body = truncated_body[:-1]
            item = f"{prefix}{truncated_body}".rstrip()
        if estimate_tokens(item) > available_tokens:
            return None
        return item

    @staticmethod
    def _truncate_text_to_token_budget(text: str, token_budget: int) -> str:
        if token_budget <= 0:
            return ""
        truncated = text[: token_budget * 2]
        while truncated and estimate_tokens(truncated) > token_budget:
            truncated = truncated[:-1]
        return truncated

    @staticmethod
    def _ordered_knowledge_results(results: Sequence[KnowledgeChunk]) -> list[KnowledgeChunk]:
        return sorted(results, key=RealCampusAgent._score_value, reverse=True)

    def _prompt_budget(self, max_tokens: int) -> int:
        return max(self.llm_context_window - max_tokens - PROMPT_MARGIN_TOKENS, 0)

    def _available_generation_prompt_tokens(self) -> int:
        return max(self.llm_context_window - self.llm_answer_max_tokens - REAL_TOKEN_HEADROOM, 0)

    def _exceeds_generation_context(self, prompt_tokens: int) -> bool:
        return prompt_tokens + self.llm_answer_max_tokens + REAL_TOKEN_HEADROOM > self.llm_context_window

    async def _count_real_tokens(self, messages: Sequence[dict[str, str]]) -> int | None:
        count_tokens = getattr(self.llm_client, "count_tokens", None)
        if not callable(count_tokens):
            return None
        prompt = "\n\n".join(str(message.get("content", "")) for message in messages)
        try:
            return await count_tokens(prompt)
        except Exception:
            return None

    @staticmethod
    def _is_context_length_exceeded(exc: BadRequestError) -> bool:
        response = getattr(exc, "response", None)
        status_code = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
        if status_code != 400:
            return False

        body = getattr(exc, "body", None)
        message = f"{exc} {body}".lower()
        return (
            "maximum context length" in message
            or ("context length" in message and "token" in message)
            or ("prompt contains" in message and "token" in message)
        )

    @staticmethod
    def _estimate_messages(messages: Sequence[dict[str, str]]) -> int:
        return sum(estimate_tokens(str(message.get("content", ""))) for message in messages)

    def _fits_prompt_budget(self, messages: Sequence[dict[str, str]], max_tokens: int) -> bool:
        return self._estimate_messages(messages) <= self._prompt_budget(max_tokens)

    def _truncate_last_user_message(
        self,
        messages: Sequence[dict[str, str]],
        max_tokens: int,
    ) -> list[dict[str, str]]:
        result = [dict(message) for message in messages]
        user_index = next((index for index in range(len(result) - 1, -1, -1) if result[index].get("role") == "user"), None)
        if user_index is None:
            return result

        fixed_tokens = self._estimate_messages(
            [message for index, message in enumerate(result) if index != user_index]
        )
        available_tokens = max(self._prompt_budget(max_tokens) - fixed_tokens, 0)
        original = str(result[user_index].get("content", ""))
        truncated = self._truncate_text_to_token_budget(original, available_tokens)
        result[user_index]["content"] = truncated
        while not self._fits_prompt_budget(result, max_tokens) and truncated:
            truncated = truncated[:-1]
            result[user_index]["content"] = truncated
        return result

    @staticmethod
    def _assemble_sources(
        knowledge_results: Sequence[KnowledgeChunk],
        web_results: Sequence[WebSearchResult],
    ) -> list[Source]:
        sources: list[Source] = []
        seen: set[tuple[str, str]] = set()
        for chunk in knowledge_results:
            if not chunk.source_urls:
                continue
            url = chunk.source_urls[0]
            key = ("knowledge", url)
            if key in seen:
                continue
            seen.add(key)
            sources.append(Source(title=chunk.title, url=url, type="knowledge"))
        for result in web_results:
            key = ("web", result.url)
            if key in seen:
                continue
            seen.add(key)
            sources.append(Source(title=result.title, url=result.url, type="web"))
        return sources

    async def _search_web_round(
        self,
        *,
        state: AgentState,
        round_number: int,
        existing_urls: set[str],
    ) -> _WebRoundOutcome:
        results: list[WebSearchResult] = []
        seen_urls = set(existing_urls)
        executed_queries: list[str] = []
        executed_query_keys: list[str] = []
        used_query_keys = set(state.get("used_web_query_keys") or [])
        queries = self._build_web_round_queries(state, round_number, reformulated=False)
        first_execution = await self._execute_web_queries(
            queries=queries,
            round_number=round_number,
            seen_urls=seen_urls,
            used_query_keys=used_query_keys,
            executed_queries=executed_queries,
            executed_query_keys=executed_query_keys,
        )
        results.extend(first_execution.results)

        if first_execution.raw_result_count == 0:
            reformulated_queries = self._build_web_round_queries(state, round_number, reformulated=True)
            reformulated_execution = await self._execute_web_queries(
                queries=reformulated_queries,
                round_number=round_number,
                seen_urls=seen_urls,
                used_query_keys=used_query_keys,
                executed_queries=executed_queries,
                executed_query_keys=executed_query_keys,
                force_unrestricted=True,
            )
            results.extend(reformulated_execution.results)

        return _WebRoundOutcome(
            candidates=results[:MAX_WEB_RESULTS_PER_ROUND],
            executed_queries=executed_queries,
            executed_query_keys=executed_query_keys,
        )

    async def _execute_web_queries(
        self,
        *,
        queries: Sequence[str],
        round_number: int,
        seen_urls: set[str],
        used_query_keys: set[str],
        executed_queries: list[str],
        executed_query_keys: list[str],
        force_unrestricted: bool = False,
    ) -> _WebExecutionOutcome:
        results: list[WebSearchResult] = []
        raw_result_count = 0
        for query in queries:
            if len(results) >= MAX_WEB_RESULTS_PER_ROUND:
                break
            search_query = self._format_web_search_query(
                query,
                round_number=round_number,
                force_unrestricted=force_unrestricted,
            )
            include_domains = (
                [OFFICIAL_SEARCH_DOMAIN]
                if round_number == 1 and not force_unrestricted
                else None
            )
            query_key = self._web_query_key(search_query, include_domains=include_domains)
            if query_key in used_query_keys:
                continue
            used_query_keys.add(query_key)
            executed_queries.append(search_query)
            executed_query_keys.append(query_key)
            rows = await self.search_provider.search(
                search_query,
                max_results=MAX_WEB_RESULTS_PER_ROUND - len(results),
                include_domains=include_domains,
            )
            raw_result_count += len(rows)
            for result in rows:
                if result.url in seen_urls:
                    continue
                seen_urls.add(result.url)
                results.append(result)
                if len(results) >= MAX_WEB_RESULTS_PER_ROUND:
                    break
        return _WebExecutionOutcome(results=results, raw_result_count=raw_result_count)

    async def _fetch_search_results(
        self,
        results: Sequence[WebSearchResult],
        *,
        keywords: Sequence[str],
    ) -> list[WebSearchResult]:
        fetched: list[WebSearchResult] = []
        for result in results:
            if result.text.strip():
                text = self._focus_page_text(result.text, keywords)
            else:
                try:
                    text = await self._fetch_page_text(result.url, keywords=keywords)
                except Exception:
                    continue
            if not text:
                continue
            fetched.append(
                WebSearchResult(
                    title=result.title,
                    url=result.url,
                    snippet=result.snippet,
                    text=text,
                )
            )
        return fetched

    async def _fetch_page_text(self, url: str, *, keywords: Sequence[str] = ()) -> str:
        async with self.http_client_factory() as client:
            response = await client.get(url)
            response.raise_for_status()
        full_text = self._extract_main_text(response.text)
        return self._focus_page_text(full_text, keywords)

    @staticmethod
    def _extract_main_text(html: str) -> str:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            parser = _FallbackTextExtractor()
            parser.feed(html)
            return parser.text

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()
        root = soup.find("main") or soup.body or soup
        text = " ".join(root.get_text(" ", strip=True).split())
        return text

    def _build_web_round_queries(
        self,
        state: AgentState,
        round_number: int,
        *,
        reformulated: bool,
    ) -> list[str]:
        base_queries = state.get("web_queries") or [state["question"]]
        if round_number == 3:
            queries = self._entity_variant_web_queries(state)
            queries.extend(base_queries)
        else:
            queries = list(base_queries)

        if round_number >= 2:
            queries = [self._ensure_university_name(query) for query in queries]

        if reformulated:
            variant_queries = [
                self._ensure_university_name(keyword)
                for keyword in generate_keyword_variants(self._web_focus_keywords(state))
            ]
            queries.extend(variant_queries)

        return self._merge_strings([], queries)

    @staticmethod
    def _format_web_search_query(
        query: str,
        *,
        round_number: int,
        force_unrestricted: bool = False,
    ) -> str:
        return query.strip()

    @staticmethod
    def _ensure_university_name(query: str) -> str:
        query = query.strip()
        if "秋田県立大学" in query:
            return query
        return f"{query} 秋田県立大学".strip()

    def _entity_variant_web_queries(self, state: AgentState) -> list[str]:
        queries: list[str] = []
        for keyword in self._unresolved_keywords(state):
            queries.append(f"{keyword} 秋田県立大学")
            stripped = strip_keyword_suffix(keyword)
            if stripped and normalize_text(stripped) != normalize_text(keyword):
                queries.append(f"{stripped} 秋田県立大学 教員")
        return self._merge_strings([], queries)

    def _prioritize_search_results(
        self,
        results: Sequence[WebSearchResult],
        keywords: Sequence[str],
    ) -> list[WebSearchResult]:
        keyword_terms = self._keyword_terms_with_variants(keywords)
        if not keyword_terms:
            return list(results)

        matched: list[WebSearchResult] = []
        unmatched: list[WebSearchResult] = []
        for result in results:
            haystack = normalize_text(f"{result.title}\n{result.snippet}")
            if any(normalize_text(keyword) in haystack for keyword in keyword_terms):
                matched.append(result)
            else:
                unmatched.append(result)
        return [*matched, *unmatched]

    @staticmethod
    def _focus_page_text(text: str, keywords: Sequence[str]) -> str:
        compact_text = " ".join(text.split())
        if len(compact_text) <= MAX_WEB_PAGE_CHARS:
            return compact_text

        keyword_terms = RealCampusAgent._keyword_terms_with_variants(keywords)
        normalized_text = normalize_text(compact_text)
        windows: list[tuple[int, int, int]] = []
        for keyword in keyword_terms:
            normalized_keyword = normalize_text(keyword)
            if not normalized_keyword:
                continue
            start = 0
            while True:
                position = normalized_text.find(normalized_keyword, start)
                if position == -1:
                    break
                window_start = max(position - (MAX_WEB_PAGE_CHARS // 2), 0)
                window_end = min(window_start + MAX_WEB_PAGE_CHARS, len(compact_text))
                window_start = max(window_end - MAX_WEB_PAGE_CHARS, 0)
                window_text = normalized_text[window_start:window_end]
                distinct_hits = sum(
                    1
                    for term in keyword_terms
                    if term and normalize_text(term) in window_text
                )
                windows.append((distinct_hits, window_start, window_end))
                start = position + max(len(normalized_keyword), 1)

        if not windows:
            return compact_text[:MAX_WEB_PAGE_CHARS]

        _, window_start, window_end = max(windows, key=lambda item: (item[0], -item[1]))
        prefix = "…" if window_start > 0 else ""
        return f"{prefix}{compact_text[window_start:window_end]}"

    @staticmethod
    def _center_excerpt_on_keywords(text: str, keywords: Sequence[str], *, limit: int) -> str:
        compact_text = " ".join(text.split())
        if len(compact_text) <= limit:
            return compact_text

        normalized_text = normalize_text(compact_text)
        positions: list[int] = []
        for keyword in RealCampusAgent._keyword_terms_with_variants(keywords):
            normalized_keyword = normalize_text(keyword)
            if not normalized_keyword:
                continue
            position = normalized_text.find(normalized_keyword)
            if position != -1:
                positions.append(position)
        if not positions:
            return compact_text[:limit]

        center = min(positions)
        start = max(center - (limit // 2), 0)
        end = min(start + limit, len(compact_text))
        start = max(end - limit, 0)
        prefix = "…" if start > 0 else ""
        return f"{prefix}{compact_text[start:end]}"

    @staticmethod
    def _keyword_terms_with_variants(keywords: Sequence[str]) -> list[str]:
        base_keywords = RealCampusAgent._merge_strings([], keywords)
        return RealCampusAgent._merge_strings(base_keywords, generate_keyword_variants(base_keywords))

    def _web_focus_keywords(self, state: AgentState) -> list[str]:
        keywords: list[str] = []
        keywords.extend(state.get("keywords") or [])
        keywords.extend(state.get("grep_keywords") or [])
        if not keywords:
            keywords.append(state["question"])
        return self._merge_strings([], keywords)

    def _retrieval_queries_for_round(
        self,
        state: AgentState,
        queries: Sequence[str] | None,
    ) -> list[str]:
        if queries is not None:
            return self._merge_strings([], queries)
        if state.get("retrieve_executed") and state.get("followup_retrieval_queries"):
            return self._merge_strings([], state.get("followup_retrieval_queries") or [])
        return self._merge_strings([], state.get("retrieval_queries") or [state["question"]])

    def _unused_retrieval_queries(
        self,
        state: AgentState,
        queries: Sequence[str],
    ) -> list[str]:
        used_keys = set(state.get("used_retrieval_queries") or [])
        unused: list[str] = []
        for query in queries:
            key = self._retrieval_query_key(query)
            if not key or key in used_keys:
                continue
            used_keys.add(key)
            unused.append(query)
        return unused

    def _has_unused_retrieval_queries(self, state: AgentState) -> bool:
        return bool(
            self._unused_retrieval_queries(
                state,
                self._retrieval_queries_for_round(state, state.get("followup_retrieval_queries") or []),
            )
        )

    @staticmethod
    def _retrieval_query_key(query: str) -> str:
        return normalize_text(" ".join(str(query).split()))

    @staticmethod
    def _web_query_key(query: str, *, include_domains: Sequence[str] | None) -> str:
        normalized_query = normalize_text(" ".join(str(query).split()))
        domain_limited = "1" if include_domains else "0"
        return f"{normalized_query}\t{domain_limited}"

    @staticmethod
    def _dedupe_keys(values: Sequence[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped

    def _search_keywords(self, state: AgentState, keywords: Sequence[str] | None) -> list[str]:
        search_keywords = list(keywords or [])
        if not search_keywords:
            search_keywords = list(state.get("keywords") or [])
        if not search_keywords:
            search_keywords = [state["question"]]
        return self._merge_strings([], search_keywords)

    def _should_run_web_search(self, state: AgentState) -> bool:
        rounds = state.get("web_search_rounds", 0)
        if rounds < MIN_WEB_ROUNDS_BEFORE_GIVE_UP:
            return True
        if rounds < MAX_WEB_SEARCH_ROUNDS and self._unresolved_keywords(state):
            return True
        return False

    def _unresolved_keywords(self, state: AgentState) -> list[str]:
        keywords = state.get("keywords") or []
        if not keywords:
            return []
        haystack = normalize_text(
            "\n".join(
                [
                    *(f"{chunk.title}\n{chunk.text}" for chunk in state.get("knowledge_results") or []),
                    *(
                        f"{result.title}\n{result.snippet}\n{result.text}"
                        for result in state.get("web_results") or []
                    ),
                ]
            )
        )
        unresolved: list[str] = []
        for keyword in keywords:
            terms = self._keyword_terms_with_variants([keyword])
            if not any(normalize_text(term) in haystack for term in terms):
                unresolved.append(keyword)
        return unresolved

    @staticmethod
    def _merge_strings(existing: Sequence[str], additions: Sequence[str]) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for value in [*existing, *additions]:
            item = " ".join(str(value).strip().split())
            if not item:
                continue
            key = normalize_text(item)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged

    def _merge_knowledge_results(
        self,
        existing_results: Sequence[KnowledgeChunk],
        new_results: Sequence[KnowledgeChunk],
    ) -> list[KnowledgeChunk]:
        by_id: dict[str, KnowledgeChunk] = {}
        for chunk in [*existing_results, *new_results]:
            current = by_id.get(chunk.id)
            if current is None:
                by_id[chunk.id] = chunk
                continue

            selected = chunk if self._score_value(chunk) > self._score_value(current) else current
            grep_keywords = tuple(
                self._merge_strings(
                    list(current.grep_keywords),
                    list(chunk.grep_keywords),
                )
            )
            by_id[chunk.id] = replace(
                selected,
                grep_hit=current.grep_hit or chunk.grep_hit,
                grep_keywords=grep_keywords,
                score=self._merged_score(current, chunk),
            )

        return self._ordered_knowledge_results(by_id.values())

    def _format_search_note(self, state: AgentState) -> str:
        if not state.get("search_executed"):
            return "全文検索: 未実行"
        terms = "、".join(state.get("search_terms") or [])
        if state.get("search_hit_count", 0) > 0:
            return f"全文検索: キーワード「{terms}」でヒットあり"
        variant_terms = "、".join(state.get("search_variant_terms") or [])
        if variant_terms:
            return f"全文検索: キーワード「{terms}」、変種「{variant_terms}」でヒットなし"
        return f"全文検索: キーワード「{terms}」でヒットなし"

    def _generation_investigation_log_line(self, state: AgentState) -> str:
        if not self._give_up_gate_satisfied(state):
            return ""
        log_line = self._build_investigation_log(state)
        return f"{log_line}\n\n" if log_line else ""

    def _give_up_gate_satisfied(self, state: AgentState) -> bool:
        return (
            not state.get("sufficient", True)
            and state.get("retrieve_executed", False)
            and state.get("search_executed", False)
            and state.get("web_search_rounds", 0) >= MIN_WEB_ROUNDS_BEFORE_GIVE_UP
        )

    def _build_investigation_log(self, state: AgentState) -> str:
        retrieval_count = state.get("retrieval_rounds", 0) or len(state.get("retrieval_queries") or [])
        search_terms = "、".join(state.get("search_terms") or [])
        variant_terms = "、".join(state.get("search_variant_terms") or [])
        web_queries = "、".join(state.get("used_web_queries") or [])
        search_detail = f"全文検索(キーワード: {search_terms or 'なし'}"
        if variant_terms:
            search_detail += f" / 変種: {variant_terms}"
        search_detail += ")"
        return (
            f"調査ログ: 学内ナレッジ検索{retrieval_count}回・{search_detail}・"
            f"Web検索{state.get('web_search_rounds', 0)}回(クエリ: {web_queries or 'なし'})"
        )

    @staticmethod
    def _dedupe_web_results(results: Sequence[WebSearchResult]) -> list[WebSearchResult]:
        deduped: list[WebSearchResult] = []
        seen_urls: set[str] = set()
        for result in results:
            if result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            deduped.append(result)
        return deduped

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any] | None:
        stripped = text.strip()
        candidates = [stripped]
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and start < end:
            candidates.append(stripped[start : end + 1])
        for candidate in candidates:
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return None

    @staticmethod
    def _normalize_queries(value: Any, *, fallback: Sequence[str], limit: int) -> list[str]:
        raw_values: list[Any]
        if isinstance(value, list):
            raw_values = value
        elif isinstance(value, str):
            raw_values = [value]
        else:
            raw_values = list(fallback)

        queries: list[str] = []
        seen: set[str] = set()
        for raw_value in raw_values:
            query = str(raw_value).strip()
            if not query or query in seen:
                continue
            seen.add(query)
            queries.append(query)
            if len(queries) >= limit:
                break
        if queries:
            return queries
        return [query for query in (str(item).strip() for item in fallback) if query][:limit]

    @staticmethod
    def _parse_bool(value: Any, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "yes", "1"}:
                return True
            if normalized in {"false", "no", "0"}:
                return False
        return default

    def _is_below_relevance_floor(self, chunk: KnowledgeChunk) -> bool:
        return chunk.score is not None and chunk.score < self.min_relevance_score

    @staticmethod
    def _score_value(chunk: KnowledgeChunk) -> float:
        return chunk.score if chunk.score is not None else float("-inf")

    @staticmethod
    def _merged_score(first: KnowledgeChunk, second: KnowledgeChunk) -> float | None:
        scores = [score for score in (first.score, second.score) if score is not None]
        return max(scores) if scores else None

    @staticmethod
    def _default_http_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=8.0, follow_redirects=True)
