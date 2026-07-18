from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from typing import Any, Literal, TypedDict

import httpx
from langgraph.config import get_stream_writer
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from openai import BadRequestError

from app.agent.campus_map import (
    ResolvedLocation,
)
from app.agent.navigator import (
    ASK_ORIGIN_RESPONSE,
    LOCATION_INDEX_SOURCE,
    CampusNavigator,
)
from app.agent.thought_stream import THOUGHT_MARKERS, THOUGHT_TEXT_LIMIT, ThoughtStreamExtractor
from app.models.auth import User
from app.models.chat import DonePayload, MapPayload, Source, StatusPayload, TokenPayload
from app.rag.lexical import generate_keyword_variants, normalize_text
from app.rag.models import KnowledgeChunk
from app.search.models import WebSearchResult
from app.services.time_context import build_time_context

Step = Literal["analyze", "retrieve", "search", "get_docs", "web_search", "evaluate", "generate"]

MAX_KNOWLEDGE_CONTEXT_CHUNKS = 24
MAX_SAME_FILE_EXPANSION_CHUNKS = 12
HIGH_RELEVANCE_CONTEXT_THRESHOLD = 0.60
MAX_WEB_RESULTS_PER_ACTION = 5
MAX_WEB_PAGES_PER_ACTION = 3
MAX_WEB_PAGE_CHARS = 1400
EVALUATE_CONTEXT_CHARS = 600
DEFAULT_LLM_CONTEXT_WINDOW = 16384
DEFAULT_LLM_ANSWER_MAX_TOKENS = 1024
PROMPT_MARGIN_TOKENS = 192
REAL_TOKEN_HEADROOM = 64
REAL_TOKEN_REBUILD_SCALE = 0.95
CONTEXT_RETRY_SCALE = 0.5
MAX_HISTORY_MESSAGES = 8
MAX_HISTORY_CHARS = 500
MIN_GENERATION_CONTEXT_TOKENS = 384
GENERATION_HISTORY_CHAR_STAGES = (MAX_HISTORY_CHARS, 250, 120)
SOFT_CONTEXT_RATIO = 0.70
HARD_CONTEXT_RATIO = 0.85
DEFAULT_RECURSION_LIMIT = 50
OBSERVATION_TOKEN_LIMIT = 500
OBSERVATION_CHUNK_EXCERPT_CHARS = 400
OBSERVATION_EXCERPT_RADIUS_CHARS = 200
GET_DOCS_OBSERVATION_TOKEN_LIMIT = 1500
ASK_USER_TOKEN_CHARS = 8
DUPLICATE_EVIDENCE_NOTE = (
    "除外分の全文は evidence 取得済みで、回答生成時にそのまま参照される（再取得不要）。"
)
FALLBACK_NOT_FOUND_RESPONSE = (
    "申し訳ありません。お探しの情報を見つけられませんでした。"
    "言い方を変えて、もう一度お試しいただけますか？"
)

DECIDE_SYSTEM_PROMPT = """あなたは秋田県立大学 本荘キャンパス（秋田県由利本荘市）のオープンキャンパス来場者案内 AI
「キャンパスガイド」の探索判断（decide）コンポーネントです。来場者は主に高校生とその保護者です。
質問とこれまでの観測を読み、次の action を必ず 1 つだけ選び、JSON のみを返してください。

注意: 本学を「APU」と略さないこと。他大学（立命館アジア太平洋大学など）と混同しないこと。
学外の一般情報（交通・宿泊・気象・比較情報など）は web_search で調べてよい。

ツール:
- retrieve {queries: string[1..3]}: 意味ベクトルで学内ナレッジを探す（言い換えに強い）
- search {keywords: string[1..6]}: 部屋番号・研究室名・固有名詞を字句一致で探す
- get_docs {file_ids: string[1..2]}: 観測に出た file_id の資料全体を読み込む（全文が必要な時だけ）
- web_search {queries: string[1..3]}: ドメイン制限なしの Web 検索（学外・最新情報）
- campus_navigator {request: string}: 学内の場所・経路の専門機構へ依頼（空間推論を自分でしない）
- ask_user {question: string}: 回答が実質的に変わる場合だけ、来場者に短く聞き返す
- finish {reason: string}: 根拠がそろったら探索を終えて回答生成へ進む

方針:
- ツール実行 0 回のまま finish しない。
- 学内の場所・経路・「どこ」「行き方」は campus_navigator に任せる。
- 推測で答えられる場合は推測と明示して答える方を優先し、ask_user を乱用しない。
- 同一の action と action_input を繰り返さない。0 件なら言い換えるか別ツールに切り替える。
- 観測の truncated=true は断片の続きがあることを示す。続き・全体が必要なら get_docs(file_ids) で全文を取得できる。
- 予算注記が「まとめに入れ」の場合は新規探索を広げず finish を優先する。
- thought は短い日本語 1〜2 文。
"""

STATUS_TEXTS: dict[Step, str] = {
    "analyze": "ご質問をじっくり読み解いています…",
    "retrieve": "キャンパスの資料を探しています…",
    "search": "学内資料をすみずみまで調べています…",
    "get_docs": "資料全体を読み込んでいます…",
    "evaluate": "集めた情報をチェックしています…",
    "web_search": "Webで最新情報を探検しています…",
    "generate": "とっておきの回答をまとめています…",
}

ASK_ORIGIN_STATUS_TEXT = "現在地を確認しています…"

logger = logging.getLogger(__name__)
trace_logger = logging.getLogger("agent.trace")


def _write_stream_event(event: str, data: dict) -> None:
    try:
        writer = get_stream_writer()
    except RuntimeError:
        # Node methods are also exercised directly by focused unit tests.
        return
    writer({"event": event, "data": data})


GENERATE_SYSTEM_PROMPT = """秋田県立大学 本荘キャンパスのオープンキャンパス2026で来場者を案内する、明るく元気な学生ガイドAI「APU-Navi」です。挨拶・自己紹介・名前を聞かれた時だけ名乗り、毎回答では名乗りません。
高校生・保護者に分かる日本語と、わくわくする親しみやすい口調で答えてください（例:「ぜひ体験してみてください！」）。
絵文字は1回答0〜3個。見出し・箇条書きの構造を保ってください。

回答ルール:
1. 禁止: 「公式サイトでご確認ください」「当日の学科紹介でご確認いただけます」など、調べれば答えられる内容を利用者に丸投げする表現を回答の主内容にしないでください。
2. コンテキストにある情報は、数字・固有名詞・手順まで具体的に盛り込み、省略しないでください。
3. 検索を尽くしても根拠がない場合のみ「現時点で確認できなかった」と正直に述べ、何をどこまで調べたか（学内ナレッジ・大学公式サイトのWeb検索）を一言添えてください。その場合に限り、補助情報として問い合わせ先を案内して構いません。
4. 年度依存情報は年度を明記し、根拠にない内容やURLを捏造しないでください。
5. 学内ナレッジは大学公式サイトの最新転記です。Web検索結果と学内ナレッジが矛盾する場合は学内ナレッジを優先し、Webの古いページ（過去の役職者・旧年度情報など）に引きずられないでください。
6. 盛り上げるのは言い回しだけです。事実（数字・固有名詞・日程）は誇張・改変しないでください。
7. 残り日数・分数・開催中/開始間近のイベントは、時間コンテキストに記載された値だけを使い、自分で日付や残り時間を計算・推測しないでください。「まであと〇日」などのカウントダウンは毎回答に入れる必要はありません。挨拶・当日の案内・日程の質問など、時間の話題が回答に自然に絡むときだけ、回答の末尾に一言、わくわく感を添えて締めくくりとして添えてください。回答の冒頭には絶対に置かず、無関係な質問に無理に差し込まないでください。
8. 場所や行き方を答えるときは、根拠に記載された棟・ゾーン・階・部屋番号（例: 学部棟Ⅰ G1ゾーン 5階 GI512）まで具体的に示してください。順路・曲がる方向・徒歩分数は根拠に記載がある場合のみ述べ、記載がない道順を創作しないでください。建物内の細かい道順が根拠にない場合は、棟・ゾーン・階・部屋番号まで案内した上で、棟内の案内表示や当日スタッフへの確認を補足してください（場所を特定できていればルール1の丸投げには当たりません）。経路の出発地が直前の会話から引き継いだものである場合、回答の冒頭でその出発地を明示してください。"""


def estimate_tokens(text: str) -> int:
    # Japanese-heavy prompts are estimated with a character heuristic.
    # A measured production prompt was 3573 chars = 2565 real Gemma tokens
    # (0.718 tokens/char), so 0.75 keeps safety margin for kanji-dense text.
    return max((len(text) * 3) // 4, 1)


class AgentState(TypedDict, total=False):
    trace_id: str
    question: str
    history: list[dict]
    knowledge_results: list[KnowledgeChunk]
    web_results: list[WebSearchResult]
    decision_count: int
    thought: str
    action: str
    action_input: dict[str, Any]
    actions_log: list[dict[str, Any]]
    action_keys: list[str]
    observations: list[str]
    known_file_ids: list[str]
    tool_executions: int
    context_usage: dict[str, Any]
    turn_terminated: bool
    terminal_kind: Literal["ask_user", "ask_origin"] | None
    clarification_blocked: bool
    navigator_sources: list[Source]
    generation_messages: list[dict[str, str]]
    generation_token_budget: int
    generation_prompt_tokens: int | None
    generation_adopted_chunk_ids: list[str]
    generation_rejected_chunk_ids: list[str]
    generation_adopted_web_urls: list[str]
    same_file_expanded_file_ids: list[str]
    same_file_expanded_chunk_ids: list[str]
    sources: list[Source]
    route_origin: ResolvedLocation | None
    route_destination: ResolvedLocation | None
    route_origin_from_history: bool
    map_payload: dict[str, Any] | None


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
class _KnowledgeMergeOutcome:
    results: list[KnowledgeChunk]
    expanded_file_ids: list[str]
    expanded_chunk_ids: list[str]


@dataclass(frozen=True)
class _KnowledgeDuplicateSummary:
    count: int
    file_ids: list[str]


@dataclass
class _ContextMeasurementCache:
    base_tokens: int | None = None
    base_actual: bool = False
    evidence_tokens: int | None = None
    evidence_actual: bool = False
    evidence_has_text: bool = False


class RealCampusAgent:
    def __init__(
        self,
        *,
        llm_client: Any,
        knowledge_store: Any,
        search_provider: Any,
        lexical_search: Any | None = None,
        top_k: int = 8,
        min_relevance_score: float = 0.45,
        http_client_factory: Callable[[], Any] | None = None,
        llm_context_window: int = DEFAULT_LLM_CONTEXT_WINDOW,
        llm_answer_max_tokens: int = DEFAULT_LLM_ANSWER_MAX_TOKENS,
        time_context_provider: Callable[[], str] | None = None,
        recursion_limit: int = DEFAULT_RECURSION_LIMIT,
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
        self.time_context_provider = time_context_provider or build_time_context
        self.recursion_limit = recursion_limit
        self.navigator = CampusNavigator(llm_client)
        self._message_metadata: dict[str, dict[str, Any]] = {}
        self._graph = self._build_graph()
        self._fallback_graph = self._build_fallback_graph()

    async def stream(
        self,
        question: str,
        user: User,
        thread_id: str,
        message_id: str,
        history: list[dict] | None = None,
    ) -> AsyncIterator[tuple[str, dict]]:
        state: AgentState = {
            "trace_id": message_id,
            "question": question.strip(),
            "history": (history or [])[-MAX_HISTORY_MESSAGES:],
            "knowledge_results": [],
            "web_results": [],
            "decision_count": 0,
            "actions_log": [],
            "action_keys": [],
            "observations": [],
            "known_file_ids": [],
            "tool_executions": 0,
            "turn_terminated": False,
            "clarification_blocked": self._previous_assistant_was_clarification(history or []),
            "navigator_sources": [],
            "same_file_expanded_file_ids": [],
            "same_file_expanded_chunk_ids": [],
        }
        merged_state = dict(state)
        try:
            async for mode, payload in self._graph.astream(
                state,
                stream_mode=["updates", "custom"],
                config={"recursion_limit": self.recursion_limit},
            ):
                if mode == "custom":
                    yield payload["event"], payload["data"]
                    continue
                if mode == "updates":
                    for update in payload.values():
                        if isinstance(update, dict):
                            merged_state.update(update)
        except GraphRecursionError:
            knowledge_count = len(merged_state.get("knowledge_results") or [])
            web_count = len(merged_state.get("web_results") or [])
            self._trace(
                "fallback_generate",
                merged_state,
                {
                    "reason": "recursion_limit",
                    "evidence_count": knowledge_count + web_count,
                    "knowledge_count": knowledge_count,
                    "web_count": web_count,
                },
            )
            if knowledge_count == 0 and web_count == 0:
                yield "status", self._status("generate")
                for start in range(0, len(FALLBACK_NOT_FOUND_RESPONSE), ASK_USER_TOKEN_CHARS):
                    yield "token", TokenPayload(
                        text=FALLBACK_NOT_FOUND_RESPONSE[start : start + ASK_USER_TOKEN_CHARS]
                    ).model_dump()
                merged_state["sources"] = []
            else:
                async for mode, payload in self._fallback_graph.astream(
                    merged_state,
                    stream_mode=["updates", "custom"],
                ):
                    if mode == "custom":
                        yield payload["event"], payload["data"]
                        continue
                    if mode == "updates":
                        for update in payload.values():
                            if isinstance(update, dict):
                                merged_state.update(update)

        if merged_state.get("terminal_kind") == "ask_user":
            self._message_metadata[message_id] = {"kind": "clarification"}

        yield "done", DonePayload(
            thread_id=thread_id,
            message_id=message_id,
            sources=merged_state.get("sources", []),
        ).model_dump()

    def consume_message_metadata(self, message_id: str) -> dict[str, Any] | None:
        return self._message_metadata.pop(message_id, None)

    @staticmethod
    def format_sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"

    def _build_graph(self) -> Any:
        workflow = StateGraph(AgentState)
        workflow.add_node("decide", self._decide)
        workflow.add_node("retrieve", self._retrieve)
        workflow.add_node("search", self._search)
        workflow.add_node("get_docs", self._get_docs)
        workflow.add_node("web_search", self._web_search)
        workflow.add_node("campus_navigator", self._campus_navigator)
        workflow.add_node("ask_user", self._ask_user)
        workflow.add_node("respond_need_origin", self._respond_need_origin)
        workflow.add_node("generate", self._generate)
        workflow.add_edge(START, "decide")
        workflow.add_conditional_edges(
            "decide",
            self._route_after_decide,
            {
                "decide": "decide",
                "retrieve": "retrieve",
                "search": "search",
                "get_docs": "get_docs",
                "web_search": "web_search",
                "campus_navigator": "campus_navigator",
                "ask_user": "ask_user",
                "finish": "generate",
            },
        )
        workflow.add_edge("retrieve", "decide")
        workflow.add_edge("search", "decide")
        workflow.add_edge("get_docs", "decide")
        workflow.add_edge("web_search", "decide")
        workflow.add_conditional_edges(
            "campus_navigator",
            self._route_after_navigator,
            {
                "decide": "decide",
                "respond_need_origin": "respond_need_origin",
            },
        )
        workflow.add_edge("ask_user", END)
        workflow.add_edge("respond_need_origin", END)
        workflow.add_edge("generate", END)
        return workflow.compile()

    def _build_fallback_graph(self) -> Any:
        workflow = StateGraph(AgentState)
        workflow.add_node("generate", self._generate)
        workflow.add_edge(START, "generate")
        workflow.add_edge("generate", END)
        return workflow.compile()

    async def _decide(self, state: AgentState) -> dict:
        decision_count = state.get("decision_count", 0)
        decision_step: Literal["analyze", "evaluate"] = (
            "analyze" if decision_count == 0 else "evaluate"
        )
        if decision_count == 0:
            _write_stream_event("status", self._status("analyze"))

        measurement_cache = _ContextMeasurementCache()
        preliminary_actions = self._available_actions(state, force_finish=False)
        preliminary_messages = self._build_decide_messages(
            state,
            preliminary_actions,
            state.get("context_usage") or {},
        )
        usage = await self._measure_context_usage(
            state,
            preliminary_messages,
            measurement_cache=measurement_cache,
        )
        force_finish = bool(usage["hard_exceeded"] or usage["evidence_full"])
        actions = self._available_actions(state, force_finish=force_finish)
        messages = self._build_decide_messages(state, actions, usage)
        usage = await self._measure_context_usage(
            state,
            messages,
            measurement_cache=measurement_cache,
        )

        parse_error: str | None = None
        try:
            extractor = ThoughtStreamExtractor()
            raw_parts: list[str] = []
            async for fragment in self.llm_client.decide_stream(
                messages,
                self._decision_schema(actions),
            ):
                raw_parts.append(fragment)
                partial_thought = extractor.feed(fragment)
                if partial_thought is not None:
                    _write_stream_event(
                        "status",
                        StatusPayload(
                            step=decision_step,
                            text=f"{partial_thought}…",
                            partial=True,
                        ).model_dump(),
                    )
            raw_output = "".join(raw_parts)
            payload = self._parse_json_object(raw_output)
        except Exception as exc:
            logger.warning("Decide transport failed: %s", exc.__class__.__name__)
            payload = None
            parse_error = exc.__class__.__name__

        if payload is None:
            fallback_action = "retrieve" if state.get("tool_executions", 0) == 0 else "finish"
            if fallback_action not in actions:
                fallback_action = actions[0]
            payload = {
                "thought": "判断形式を整え、探索を安全に続けます。",
                "action": fallback_action,
                "action_input": (
                    {"queries": [state["question"]]}
                    if fallback_action == "retrieve"
                    else {"reason": "判断形式を復旧して回答生成へ進む"}
                ),
            }
            parse_error = parse_error or "invalid_json"

        validation_error = self._validate_decision(payload, actions)
        thought = self._sanitize_thought(payload.get("thought"))
        action = str(payload.get("action") or "")
        action_input = payload.get("action_input") if isinstance(payload.get("action_input"), dict) else {}

        if validation_error is None and action == "finish" and state.get("tool_executions", 0) == 0:
            validation_error = "ツール実行 0 回のまま finish はできません。まず情報を集めてください。"

        if validation_error is None and action == "get_docs":
            requested_file_ids = list(action_input.get("file_ids") or [])
            known_file_ids = self._known_file_ids(state)
            known_set = set(known_file_ids)
            unknown_file_ids = [file_id for file_id in requested_file_ids if file_id not in known_set]
            if unknown_file_ids:
                known_label = ", ".join(known_file_ids) if known_file_ids else "なし"
                validation_error = (
                    f"未知の file_id です: {', '.join(unknown_file_ids)}。"
                    f"既知 file_id: {known_label}。"
                )

        action_key = self._action_key(action, action_input)
        if validation_error is None and action_key in set(state.get("action_keys") or []):
            validation_error = "同一の action と action_input は試行済みです。別の手段を選んでください。"

        observations = list(state.get("observations") or [])
        actions_log = list(state.get("actions_log") or [])
        action_keys = list(state.get("action_keys") or [])
        routed_action = action
        if validation_error is not None:
            observations.append(self._compact_observation(f"エラー観測: {validation_error}"))
            routed_action = "decide"
        else:
            action_keys.append(action_key)
            actions_log.append(
                {
                    "thought": thought,
                    "action": action,
                    "action_input": action_input,
                    "result": "selected",
                }
            )

        _write_stream_event(
            "status",
            StatusPayload(step=decision_step, text=thought).model_dump(),
        )

        self._trace(
            "decide",
            state,
            {
                "thought": thought,
                "action": action,
                "action_input": action_input,
                "available_actions": actions,
                "budget": usage,
                "validation_error": validation_error,
                "parse_error": parse_error,
            },
        )
        return {
            "decision_count": decision_count + 1,
            "thought": thought,
            "action": routed_action,
            "action_input": action_input,
            "actions_log": actions_log,
            "action_keys": action_keys,
            "observations": observations,
            "context_usage": usage,
        }

    async def _retrieve(self, state: AgentState) -> dict:
        queries = list(state.get("action_input", {}).get("queries") or [])
        _write_stream_event("status", self._tool_status("retrieve", queries))
        existing_results = state.get("knowledge_results") or []
        try:
            retrieved_results: list[KnowledgeChunk] = []
            trace_queries: list[dict[str, Any]] = []
            for query in queries:
                results = await self.knowledge_store.search(query, limit=self.top_k)
                trace_queries.append(
                    {
                        "query": query,
                        "hits": [self._trace_chunk_hit(chunk) for chunk in results[: self.top_k]],
                    }
                )
                retrieved_results.extend(
                    chunk for chunk in results if not self._is_below_relevance_floor(chunk)
                )
            merge_outcome = self._merge_and_expand_knowledge_results(
                state,
                existing_results,
                retrieved_results,
            )
            old_ids = {chunk.id for chunk in existing_results}
            new_chunks = [chunk for chunk in merge_outcome.results if chunk.id not in old_ids]
            duplicate_summary = self._knowledge_duplicate_summary(
                existing_results,
                retrieved_results,
            )
            observation = self._knowledge_observation(
                "意味検索",
                new_chunks,
                duplicate_count=duplicate_summary.count,
                duplicate_file_ids=duplicate_summary.file_ids,
                terms=queries,
            )
            self._trace("retrieve", state, {"queries": trace_queries, "observation": observation})
            return {
                "knowledge_results": merge_outcome.results,
                "tool_executions": state.get("tool_executions", 0) + 1,
                "observations": [*(state.get("observations") or []), observation],
                "actions_log": self._complete_action_log(state, observation),
                "known_file_ids": self._merge_known_file_ids(
                    state,
                    self._knowledge_observation_file_ids(new_chunks, duplicate_summary.file_ids),
                ),
                "same_file_expanded_file_ids": merge_outcome.expanded_file_ids,
                "same_file_expanded_chunk_ids": merge_outcome.expanded_chunk_ids,
            }
        except Exception as exc:
            return self._tool_error_patch(state, "retrieve", exc)

    async def _search(self, state: AgentState) -> dict:
        keywords = list(state.get("action_input", {}).get("keywords") or [])
        _write_stream_event("status", self._tool_status("search", keywords))
        existing_results = state.get("knowledge_results") or []
        try:
            if self.lexical_search is None:
                grep_chunks: list[KnowledgeChunk] = []
                variants: list[str] = []
                trace_hits: list[dict[str, Any]] = []
            else:
                outcome = self.lexical_search.grep_sections_with_trace(keywords)
                grep_chunks = [hit.chunk for hit in outcome.hits]
                variants = outcome.variant_keywords
                trace_hits = [
                    {
                        "file_id": hit.chunk.file_id,
                        "chunk_index": hit.chunk.chunk_index,
                        "distinct": hit.distinct_keyword_hits,
                        "total": hit.total_hits,
                    }
                    for hit in outcome.hits
                ]
            merge_outcome = self._merge_and_expand_knowledge_results(
                state,
                existing_results,
                grep_chunks,
            )
            old_ids = {chunk.id for chunk in existing_results}
            new_chunks = [chunk for chunk in merge_outcome.results if chunk.id not in old_ids]
            duplicate_summary = self._knowledge_duplicate_summary(
                existing_results,
                grep_chunks,
            )
            observation = self._knowledge_observation(
                "字句検索",
                new_chunks,
                duplicate_count=duplicate_summary.count,
                duplicate_file_ids=duplicate_summary.file_ids,
                terms=[*keywords, *variants],
                variants=variants,
            )
            self._trace(
                "search",
                state,
                {
                    "keywords": keywords,
                    "variants": variants,
                    "hits": trace_hits,
                    "observation": observation,
                },
            )
            return {
                "knowledge_results": merge_outcome.results,
                "tool_executions": state.get("tool_executions", 0) + 1,
                "observations": [*(state.get("observations") or []), observation],
                "actions_log": self._complete_action_log(state, observation),
                "known_file_ids": self._merge_known_file_ids(
                    state,
                    self._knowledge_observation_file_ids(new_chunks, duplicate_summary.file_ids),
                ),
                "same_file_expanded_file_ids": merge_outcome.expanded_file_ids,
                "same_file_expanded_chunk_ids": merge_outcome.expanded_chunk_ids,
            }
        except Exception as exc:
            return self._tool_error_patch(state, "search", exc)

    async def _get_docs(self, state: AgentState) -> dict:
        file_ids = list(state.get("action_input", {}).get("file_ids") or [])
        _write_stream_event("status", self._tool_status("get_docs", file_ids))
        known_file_ids = self._known_file_ids(state)
        unknown_file_ids = [file_id for file_id in file_ids if file_id not in set(known_file_ids)]
        if unknown_file_ids:
            known_label = ", ".join(known_file_ids) if known_file_ids else "なし"
            observation = self._compact_observation(
                f"エラー観測: 未知の file_id です: {', '.join(unknown_file_ids)}。"
                f"既知 file_id: {known_label}。"
            )
            self._trace(
                "get_docs",
                state,
                {
                    "file_ids": file_ids,
                    "unknown_file_ids": unknown_file_ids,
                    "observation": observation,
                },
            )
            return {
                "observations": [*(state.get("observations") or []), observation],
                "actions_log": self._complete_action_log(state, observation, error=True),
            }

        try:
            chunks = await self._fetch_file_chunks(file_ids)
            existing_results = state.get("knowledge_results") or []
            old_ids = {chunk.id for chunk in existing_results}
            merged_results = self._merge_knowledge_results(existing_results, chunks)
            observation, result_meta = self._get_docs_observation(file_ids, chunks)
            chunks_added = len([chunk for chunk in chunks if chunk.id not in old_ids])
            self._trace(
                "get_docs",
                state,
                {
                    "file_ids": file_ids,
                    "chunks_added": chunks_added,
                    "total_chunks": len(chunks),
                    "observation_tokens": estimate_tokens(observation),
                },
            )
            fetched_file_ids = self._dedupe_keys(chunk.file_id or "" for chunk in chunks)
            return {
                "knowledge_results": merged_results,
                "tool_executions": state.get("tool_executions", 0) + 1,
                "observations": [*(state.get("observations") or []), observation],
                "actions_log": self._complete_action_log(state, result_meta),
                "known_file_ids": self._merge_known_file_ids(state, file_ids),
                "same_file_expanded_file_ids": self._dedupe_keys(
                    [*(state.get("same_file_expanded_file_ids") or []), *fetched_file_ids]
                ),
                "same_file_expanded_chunk_ids": self._dedupe_keys(
                    [
                        *(state.get("same_file_expanded_chunk_ids") or []),
                        *(chunk.id for chunk in chunks),
                    ]
                ),
            }
        except Exception as exc:
            return self._tool_error_patch(state, "get_docs", exc)

    async def _web_search(self, state: AgentState) -> dict:
        queries = list(state.get("action_input", {}).get("queries") or [])
        _write_stream_event("status", self._tool_status("web_search", queries))
        try:
            soft_exceeded = bool((state.get("context_usage") or {}).get("soft_exceeded"))
            if not getattr(self.search_provider, "available", True):
                observation = "Web 検索は現在利用不可です。別の根拠で続行してください。"
                return {
                    "tool_executions": state.get("tool_executions", 0) + 1,
                    "observations": [*(state.get("observations") or []), observation],
                    "actions_log": self._complete_action_log(state, observation),
                }

            candidates: list[WebSearchResult] = []
            seen_urls = {result.url for result in state.get("web_results") or []}
            duplicate_count = 0
            for query in queries:
                rows = await self.search_provider.search(
                    query,
                    max_results=MAX_WEB_RESULTS_PER_ACTION,
                    include_domains=None,
                    include_raw_content=not soft_exceeded,
                )
                for result in rows:
                    if result.url in seen_urls:
                        duplicate_count += 1
                        continue
                    seen_urls.add(result.url)
                    candidates.append(result)
                    if len(candidates) >= MAX_WEB_RESULTS_PER_ACTION:
                        break
                if len(candidates) >= MAX_WEB_RESULTS_PER_ACTION:
                    break

            prioritized = self._prioritize_search_results(candidates, queries)
            fetched_results = await self._fetch_search_results(
                prioritized[:MAX_WEB_PAGES_PER_ACTION],
                keywords=queries,
                fetch_missing=not soft_exceeded,
            )
            existing = state.get("web_results") or []
            web_results = self._dedupe_web_results([*existing, *fetched_results])
            old_urls = {result.url for result in existing}
            new_results = [result for result in web_results if result.url not in old_urls]
            observation = self._web_observation(
                new_results,
                duplicate_count=duplicate_count + max(len(fetched_results) - len(new_results), 0),
            )
            self._trace(
                "web_search",
                state,
                {
                    "queries": queries,
                    "urls": [result.url for result in new_results],
                    "raw_content_suppressed": soft_exceeded,
                    "observation": observation,
                },
            )
            return {
                "web_results": web_results,
                "tool_executions": state.get("tool_executions", 0) + 1,
                "observations": [*(state.get("observations") or []), observation],
                "actions_log": self._complete_action_log(state, observation),
            }
        except Exception as exc:
            return self._tool_error_patch(state, "web_search", exc)

    async def _campus_navigator(self, state: AgentState) -> dict:
        request = str(state.get("action_input", {}).get("request") or "")
        _write_stream_event(
            "status",
            StatusPayload(step="analyze", text="キャンパスマップで経路を調べています…").model_dump(),
        )

        def write_internal_status(text: str, partial: bool) -> None:
            _write_stream_event(
                "status",
                StatusPayload(step="analyze", text=text, partial=partial).model_dump(),
            )

        try:
            result = await self.navigator.navigate(
                request=request,
                question=state["question"],
                history=state.get("history") or [],
                status_callback=write_internal_status,
            )
            result_type = str(result.get("type") or "not_navigable")
            self._trace(
                "campus_navigator",
                state,
                {
                    "fast_path": result.get("fast_path"),
                    "result_type": result_type,
                    "internal_trace": result.get("trace") or [],
                },
            )
            observation = self._navigator_observation(result)
            patch: dict[str, Any] = {
                "tool_executions": state.get("tool_executions", 0) + 1,
                "observations": [*(state.get("observations") or []), observation],
                "actions_log": self._complete_action_log(state, observation),
            }
            if result_type in {"route", "place", "need_origin"}:
                map_payload = result.get("map_payload")
                MapPayload(**map_payload)
                patch.update(
                    {
                        "map_payload": map_payload,
                        "route_destination": result.get("destination"),
                        "navigator_sources": list(result.get("sources") or []),
                    }
                )
            if result_type == "route":
                patch.update(
                    {
                        "route_origin": result.get("origin"),
                        "route_origin_from_history": bool(result.get("origin_from_history")),
                    }
                )
            elif result_type == "need_origin":
                patch.update(
                    {
                        "turn_terminated": True,
                        "terminal_kind": "ask_origin",
                    }
                )
            return patch
        except Exception as exc:
            return self._tool_error_patch(state, "campus_navigator", exc)

    async def _ask_user(self, state: AgentState) -> dict:
        question = str(state.get("action_input", {}).get("question") or "").strip()
        _write_stream_event("status", self._status("generate"))
        for start in range(0, len(question), ASK_USER_TOKEN_CHARS):
            _write_stream_event(
                "token",
                TokenPayload(text=question[start : start + ASK_USER_TOKEN_CHARS]).model_dump(),
            )
        return {
            "turn_terminated": True,
            "terminal_kind": "ask_user",
            "sources": [],
            "actions_log": self._complete_action_log(state, "clarification を送出"),
        }

    async def _respond_need_origin(self, state: AgentState) -> dict:
        _write_stream_event(
            "status",
            StatusPayload(step="generate", text=ASK_ORIGIN_STATUS_TEXT).model_dump(),
        )
        _write_stream_event("token", TokenPayload(text=ASK_ORIGIN_RESPONSE).model_dump())
        _write_stream_event("map", state["map_payload"])
        sources = list(state.get("navigator_sources") or [])
        if not sources:
            sources = self._assemble_generation_sources(state, None)
        return {"sources": sources}

    async def _route_after_decide(self, state: AgentState) -> str:
        action = state.get("action") or "decide"
        return action if action in {
            "decide",
            "retrieve",
            "search",
            "web_search",
            "get_docs",
            "campus_navigator",
            "ask_user",
            "finish",
        } else "decide"

    async def _route_after_navigator(self, state: AgentState) -> str:
        return "respond_need_origin" if state.get("turn_terminated") else "decide"

    @staticmethod
    def _decision_schema(actions: Sequence[str]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
                "action": {"type": "string", "enum": list(actions)},
                "action_input": {"type": "object", "additionalProperties": True},
            },
            "required": ["thought", "action", "action_input"],
            "additionalProperties": False,
        }

    def _available_actions(self, state: AgentState, *, force_finish: bool) -> list[str]:
        actions = (
            ["finish", "ask_user"]
            if force_finish
            else [
                "retrieve",
                "search",
                *(
                    ["get_docs"]
                    if self._known_file_ids(state)
                    else []
                ),
                "web_search",
                "campus_navigator",
                "ask_user",
                "finish",
            ]
        )
        if state.get("clarification_blocked"):
            actions = [action for action in actions if action != "ask_user"]
        return actions

    def _validate_decision(
        self,
        payload: dict[str, Any],
        available_actions: Sequence[str],
    ) -> str | None:
        if set(payload) != {"thought", "action", "action_input"}:
            return "判断 JSON のキーが仕様と一致しません。"
        if not isinstance(payload.get("thought"), str):
            return "thought は文字列で指定してください。"
        action = payload.get("action")
        if action not in available_actions:
            return f"action {action!r} は現在のメニューにありません。"
        action_input = payload.get("action_input")
        if not isinstance(action_input, dict):
            return "action_input はオブジェクトで指定してください。"
        if action in {"retrieve", "web_search"}:
            queries = action_input.get("queries")
            if not self._valid_string_list(queries, minimum=1, maximum=3):
                return "queries は空でない文字列 1〜3 件で指定してください。"
        elif action == "search":
            if not self._valid_string_list(action_input.get("keywords"), minimum=1, maximum=6):
                return "keywords は空でない文字列 1〜6 件で指定してください。"
        elif action == "get_docs":
            if not self._valid_string_list(action_input.get("file_ids"), minimum=1, maximum=2):
                return "file_ids は空でない文字列 1〜2 件で指定してください。"
        else:
            key = {
                "campus_navigator": "request",
                "ask_user": "question",
                "finish": "reason",
            }[action]
            value = action_input.get(key)
            if not isinstance(value, str) or not value.strip():
                return f"{key} は空でない文字列で指定してください。"
        return None

    @staticmethod
    def _valid_string_list(value: Any, *, minimum: int, maximum: int) -> bool:
        return (
            isinstance(value, list)
            and minimum <= len(value) <= maximum
            and all(isinstance(item, str) and item.strip() for item in value)
        )

    @staticmethod
    def _action_key(action: str, action_input: dict[str, Any]) -> str:
        return f"{action}\t{json.dumps(action_input, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"

    @staticmethod
    def _previous_assistant_was_clarification(history: Sequence[dict]) -> bool:
        for message in reversed(history):
            if message.get("role") != "assistant":
                continue
            metadata = message.get("metadata")
            return isinstance(metadata, dict) and metadata.get("kind") == "clarification"
        return False

    def _build_decide_messages(
        self,
        state: AgentState,
        actions: Sequence[str],
        usage: dict[str, Any],
    ) -> list[dict[str, str]]:
        system_note = f"\n現在選択可能な action: {', '.join(actions)}"
        if usage.get("soft_exceeded"):
            system_note += "\n予算注記: まとめに入れ。新規探索を広げず finish を優先してください。"
        if usage.get("hard_exceeded") or usage.get("evidence_full"):
            system_note += "\n予算注記: 探索予算を使い切りました。finish を優先してください。"
        messages: list[dict[str, str]] = [
            {"role": "system", "content": f"{DECIDE_SYSTEM_PROMPT}{system_note}"}
        ]
        messages.extend(self._format_history(state.get("history") or []))
        action_log = json.dumps(
            state.get("actions_log") or [],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        observations = "\n".join(
            f"{index}. {observation}"
            for index, observation in enumerate(state.get("observations") or [], start=1)
        ) or "なし"
        messages.append(
            {
                "role": "user",
                "content": (
                    f"質問:\n{state['question']}\n\n"
                    f"行動ログ:\n{action_log}\n\n"
                    f"観測:\n{observations}\n\n"
                    f"予算状態: {json.dumps(usage, ensure_ascii=False, separators=(',', ':'))}"
                ),
            }
        )
        return messages

    async def _measure_context_usage(
        self,
        state: AgentState,
        decide_messages: Sequence[dict[str, str]],
        *,
        measurement_cache: _ContextMeasurementCache | None = None,
    ) -> dict[str, Any]:
        decide_text = "\n\n".join(message.get("content", "") for message in decide_messages)
        tokens, actual = await self._count_text_tokens(decide_text)

        cache = measurement_cache or _ContextMeasurementCache()
        if cache.base_tokens is None or cache.evidence_tokens is None:
            full_context = self._assemble_context_with_budget(
                state.get("knowledge_results") or [],
                state.get("web_results") or [],
                mode="generate",
                token_budget=None,
            )
            base_messages, _ = self._build_generation_messages_with_sources(state, token_budget=0)
            base_text = "\n\n".join(message.get("content", "") for message in base_messages)
            cache.base_tokens, cache.base_actual = await self._count_text_tokens(base_text)
            cache.evidence_tokens, cache.evidence_actual = await self._count_text_tokens(
                full_context.text
            )
            cache.evidence_has_text = bool(full_context.text)
        base_tokens = cache.base_tokens
        evidence_tokens = cache.evidence_tokens
        assert base_tokens is not None
        assert evidence_tokens is not None
        evidence_budget = max(self._available_generation_prompt_tokens() - base_tokens, 0)
        ratio = tokens / self.llm_context_window if self.llm_context_window > 0 else 1.0
        return {
            "tokens": tokens,
            "actual": actual,
            "window": self.llm_context_window,
            "ratio": round(ratio, 4),
            "soft_exceeded": ratio >= SOFT_CONTEXT_RATIO,
            "hard_exceeded": ratio >= HARD_CONTEXT_RATIO,
            "evidence_tokens": evidence_tokens,
            "evidence_actual": cache.evidence_actual,
            "generation_base_actual": cache.base_actual,
            "generation_evidence_budget": evidence_budget,
            "evidence_full": cache.evidence_has_text and evidence_tokens >= evidence_budget,
        }

    async def _count_text_tokens(self, text: str) -> tuple[int, bool]:
        count_tokens = getattr(self.llm_client, "count_tokens", None)
        if callable(count_tokens):
            try:
                count = await count_tokens(text)
            except Exception:
                count = None
            if isinstance(count, int):
                return count, True
        return estimate_tokens(text), False

    @staticmethod
    def _sanitize_thought(value: Any) -> str:
        text = " ".join(str(value or "").split())
        if not text or any(marker in text for marker in THOUGHT_MARKERS):
            return STATUS_TEXTS["evaluate"]
        if len(text) > THOUGHT_TEXT_LIMIT:
            return f"{text[:THOUGHT_TEXT_LIMIT]}…"
        return text

    def _compact_observation(self, text: str) -> str:
        compact = " ".join(text.split())
        return self._truncate_text_to_token_budget(compact, OBSERVATION_TOKEN_LIMIT)

    def _knowledge_observation(
        self,
        label: str,
        chunks: Sequence[KnowledgeChunk],
        *,
        duplicate_count: int,
        duplicate_file_ids: Sequence[str] = (),
        terms: Sequence[str] = (),
        variants: Sequence[str] = (),
    ) -> str:
        file_totals = self._file_chunk_totals(
            chunk.file_id for chunk in chunks[:3] if chunk.file_id
        )
        details = [
            self._knowledge_observation_detail(
                chunk,
                terms=terms,
                file_total=file_totals.get(chunk.file_id or ""),
            )
            for chunk in chunks[:3]
        ]
        variant_note = f" 表記ゆれ={','.join(variants)}。" if variants else ""
        duplicate_note = (
            f" {self._duplicate_evidence_note(duplicate_file_ids)}"
            if duplicate_count > 0
            else ""
        )
        return self._compact_observation(
            f"{label}: 新規{len(chunks)}件、重複除外{duplicate_count}件。"
            f"{duplicate_note}{variant_note}{' / '.join(details) if details else '該当なし'}"
        )

    def _knowledge_observation_detail(
        self,
        chunk: KnowledgeChunk,
        *,
        terms: Sequence[str],
        file_total: int | None,
    ) -> str:
        keywords = chunk.grep_keywords or tuple(terms)
        excerpt, truncated = self._observation_excerpt(chunk.text, keywords)
        file_id = chunk.file_id or "unknown"
        chunk_position = self._chunk_position_label(chunk, file_total=file_total)
        return (
            f"file_id={file_id} chunk={chunk_position} truncated={str(truncated).lower()} "
            f"{chunk.title}: {excerpt}"
        )

    @staticmethod
    def _observation_excerpt(text: str, keywords: Sequence[str]) -> tuple[str, bool]:
        compact_text = " ".join(text.split())
        if len(compact_text) <= OBSERVATION_CHUNK_EXCERPT_CHARS:
            return compact_text, False

        keyword_terms = RealCampusAgent._keyword_terms_with_variants(keywords)
        normalized_text, original_offsets = RealCampusAgent._normalize_with_original_offsets(compact_text)
        positions = [
            RealCampusAgent._normalized_match_center_offset(
                original_offsets,
                position,
                len(normalize_text(keyword)),
            )
            for keyword in keyword_terms
            if (position := normalized_text.find(normalize_text(keyword))) != -1
        ]
        if positions:
            center = min(positions)
            start = max(center - OBSERVATION_EXCERPT_RADIUS_CHARS, 0)
            end = min(start + OBSERVATION_CHUNK_EXCERPT_CHARS, len(compact_text))
            start = max(end - OBSERVATION_CHUNK_EXCERPT_CHARS, 0)
        else:
            start = 0
            end = min(OBSERVATION_CHUNK_EXCERPT_CHARS, len(compact_text))

        truncated = start > 0 or end < len(compact_text)
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(compact_text) else ""
        return f"{prefix}{compact_text[start:end]}{suffix}", truncated

    @staticmethod
    def _normalize_with_original_offsets(text: str) -> tuple[str, list[int]]:
        normalized_parts: list[str] = []
        original_offsets: list[int] = []
        for original_index, char in enumerate(text):
            normalized_char = normalize_text(char)
            normalized_parts.append(normalized_char)
            original_offsets.extend([original_index] * len(normalized_char))
        return "".join(normalized_parts), original_offsets

    @staticmethod
    def _normalized_match_center_offset(
        original_offsets: Sequence[int],
        normalized_position: int,
        normalized_length: int,
    ) -> int:
        if not original_offsets:
            return 0
        start = original_offsets[min(normalized_position, len(original_offsets) - 1)]
        end_position = min(
            normalized_position + max(normalized_length, 1) - 1,
            len(original_offsets) - 1,
        )
        end = original_offsets[end_position]
        return (start + end) // 2

    def _file_chunk_totals(self, file_ids: Sequence[str]) -> dict[str, int]:
        target_file_ids = set(file_ids)
        if not target_file_ids:
            return {}

        load_sections = getattr(self.lexical_search, "_load_sections", None)
        if not callable(load_sections):
            return {}

        totals: dict[str, int] = {}
        for section in load_sections():
            chunk = getattr(section, "chunk", None)
            file_id = getattr(chunk, "file_id", None)
            if file_id not in target_file_ids:
                continue
            totals[file_id] = totals.get(file_id, 0) + 1
        return totals

    @staticmethod
    def _chunk_position_label(chunk: KnowledgeChunk, *, file_total: int | None) -> str:
        if chunk.chunk_index is None:
            return "?/?"
        index = chunk.chunk_index + 1
        if file_total is None:
            return f"{index}/?"
        return f"{index}/{file_total}"

    @staticmethod
    def _duplicate_evidence_note(file_ids: Sequence[str]) -> str:
        file_id_note = f" file_id={','.join(file_ids)}。" if file_ids else ""
        return f"{DUPLICATE_EVIDENCE_NOTE}{file_id_note}"

    async def _fetch_file_chunks(self, file_ids: Sequence[str]) -> list[KnowledgeChunk]:
        fetch = getattr(self.knowledge_store, "get_file_chunks", None)
        if not callable(fetch):
            raise RuntimeError("knowledge_store does not support get_file_chunks")
        chunks = await fetch(file_ids)
        return self._sort_file_chunks(file_ids, chunks)

    @staticmethod
    def _sort_file_chunks(
        file_ids: Sequence[str],
        chunks: Sequence[KnowledgeChunk],
    ) -> list[KnowledgeChunk]:
        file_order = {file_id: index for index, file_id in enumerate(file_ids)}
        return sorted(
            chunks,
            key=lambda chunk: (
                file_order.get(chunk.file_id or "", len(file_order)),
                chunk.chunk_index is None,
                chunk.chunk_index if chunk.chunk_index is not None else 0,
                chunk.id,
            ),
        )

    def _get_docs_observation(
        self,
        file_ids: Sequence[str],
        chunks: Sequence[KnowledgeChunk],
    ) -> tuple[str, str]:
        chunks_by_file: dict[str, list[KnowledgeChunk]] = {file_id: [] for file_id in file_ids}
        for chunk in chunks:
            if chunk.file_id in chunks_by_file:
                chunks_by_file[chunk.file_id].append(chunk)

        meta_lines = [
            f"file {file_id}: 全 {len(chunks_by_file[file_id])} チャンクを evidence に取得済み（回答生成時に全文参照）"
            for file_id in file_ids
        ]
        body_parts: list[str] = []
        file_totals = {file_id: len(file_chunks) for file_id, file_chunks in chunks_by_file.items()}
        for file_id in file_ids:
            for chunk in chunks_by_file[file_id]:
                body_parts.append(
                    f"[file_id={file_id} chunk={self._chunk_position_label(chunk, file_total=file_totals[file_id])}] "
                    f"{chunk.title}: {' '.join(chunk.text.split())}"
                )

        body_text = "\n".join(body_parts) if body_parts else "該当チャンクなし"
        meta_prefix = "get_docs: " + " / ".join(meta_lines)
        body_budget = max(
            GET_DOCS_OBSERVATION_TOKEN_LIMIT
            - estimate_tokens(f"{meta_prefix} truncated=true。本文先頭: "),
            0,
        )
        truncated = estimate_tokens(body_text) > body_budget
        body_excerpt = self._truncate_text_to_token_budget(body_text, body_budget)
        result_meta = f"{meta_prefix} truncated={str(truncated).lower()}"
        observation = f"{result_meta}。本文先頭: {body_excerpt}"
        return (
            self._truncate_text_to_token_budget(observation, GET_DOCS_OBSERVATION_TOKEN_LIMIT),
            result_meta,
        )

    def _web_observation(
        self,
        results: Sequence[WebSearchResult],
        *,
        duplicate_count: int,
    ) -> str:
        details = [
            f"{result.title} ({result.url}): {' '.join((result.snippet or result.text).split())[:140]}"
            for result in results[:3]
        ]
        duplicate_note = f" {DUPLICATE_EVIDENCE_NOTE}" if duplicate_count > 0 else ""
        return self._compact_observation(
            f"Web検索: 新規{len(results)}件、重複除外{duplicate_count}件。"
            f"{duplicate_note}{' / '.join(details) if details else '該当なし'}"
        )

    def _navigator_observation(self, result: dict[str, Any]) -> str:
        result_type = result.get("type")
        if result_type == "route":
            return self._compact_observation(
                f"campus_navigator route: {result.get('steps_text') or '経路を解決'}"
            )
        if result_type == "place":
            return self._compact_observation(
                f"campus_navigator place: {result.get('fact') or '場所を解決'}"
            )
        if result_type == "need_origin":
            destination = result.get("destination")
            label = destination.label if isinstance(destination, ResolvedLocation) else "目的地"
            return f"campus_navigator need_origin: {label} への出発地を確認します。"
        return self._compact_observation(
            f"campus_navigator not_navigable: {result.get('reason') or '解決不能'}"
        )

    def _complete_action_log(
        self,
        state: AgentState,
        result: str,
        *,
        error: bool = False,
    ) -> list[dict[str, Any]]:
        log = [dict(item) for item in state.get("actions_log") or []]
        if log:
            log[-1]["result"] = "error" if error else self._compact_observation(result)
        return log

    def _tool_error_patch(
        self,
        state: AgentState,
        step: str,
        exc: Exception,
    ) -> dict[str, Any]:
        observation = self._compact_observation(
            f"{step} は {exc.__class__.__name__} で失敗しました。別手段で degraded 続行してください。"
        )
        logger.warning("%s tool failed: %s", step, exc.__class__.__name__)
        self._trace(step, state, {"error": exc.__class__.__name__, "observation": observation})
        return {
            "tool_executions": state.get("tool_executions", 0) + 1,
            "observations": [*(state.get("observations") or []), observation],
            "actions_log": self._complete_action_log(state, observation, error=True),
        }

    @staticmethod
    def _tool_status(
        step: Literal["retrieve", "search", "get_docs", "web_search"],
        terms: Sequence[str],
    ) -> dict:
        summary = "、".join(terms[:2])
        text = STATUS_TEXTS[step]
        if summary:
            text = f"{text.removesuffix('…')}（{summary}）…"
        return StatusPayload(step=step, text=text).model_dump()
    async def _prepare_generation(self, state: AgentState) -> dict:
        messages, context = self._build_generation_messages_with_sources(state)
        sources = self._assemble_generation_sources(state, context)
        generation_trace = self._generation_context_trace(state, context)
        return {
            "generation_messages": messages,
            "generation_token_budget": estimate_tokens(context.text),
            **generation_trace,
            "sources": sources,
        }

    async def _verify_generation_prompt(self, state: AgentState) -> dict:
        messages = state.get("generation_messages") or self._build_generation_messages(state)
        count = await self._count_real_tokens(messages)
        if count is None or not self._exceeds_generation_context(count):
            return {"generation_prompt_tokens": count}

        available_prompt_tokens = self._available_generation_prompt_tokens()
        factor = (available_prompt_tokens / count) * REAL_TOKEN_REBUILD_SCALE if count > 0 else 0
        current_budget = int(state.get("generation_token_budget", 0))
        reduced_budget = max(int(current_budget * factor), 0)
        messages, context = self._build_generation_messages_with_sources(state, token_budget=reduced_budget)
        sources = self._assemble_generation_sources(state, context)
        rebuilt_count = await self._count_real_tokens(messages)
        return {
            "generation_messages": messages,
            "generation_token_budget": reduced_budget,
            "generation_prompt_tokens": rebuilt_count,
            **self._generation_context_trace(state, context),
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
            state["sources"] = self._assemble_generation_sources(state, retry_context)
            async for token in self.llm_client.stream_chat(
                retry_messages,
                temperature=0.7,
                max_tokens=self.llm_answer_max_tokens,
            ):
                yield token

    async def _generate(self, state: AgentState) -> dict:
        _write_stream_event("status", self._status("generate"))
        generation_updates = await self._prepare_generation(state)
        working_state: AgentState = {**state, **generation_updates}
        verification_updates = await self._verify_generation_prompt(working_state)
        generation_updates.update(verification_updates)
        working_state.update(verification_updates)
        self._trace(
            "generate",
            working_state,
            {
                "adopted_chunk_ids": working_state.get("generation_adopted_chunk_ids", []),
                "rejected_chunk_ids": working_state.get("generation_rejected_chunk_ids", []),
                "adopted_web_urls": working_state.get("generation_adopted_web_urls", []),
                "prompt_tokens": working_state.get("generation_prompt_tokens"),
            },
        )

        messages = working_state.get("generation_messages") or self._build_generation_messages(working_state)
        async for token in self._stream_generation_with_retry(working_state, messages):
            _write_stream_event("token", TokenPayload(text=token).model_dump())

        if working_state.get("map_payload") is not None:
            _write_stream_event("map", working_state["map_payload"])

        for key in ("generation_messages", "generation_token_budget", "sources"):
            if key in working_state:
                generation_updates[key] = working_state[key]
        return generation_updates

    @staticmethod
    def _status(step: Step) -> dict:
        return StatusPayload(step=step, text=STATUS_TEXTS[step]).model_dump()

    def _build_generation_messages(self, state: AgentState) -> list[dict[str, str]]:
        messages, _ = self._build_generation_messages_with_sources(state)
        return messages

    def _build_generation_messages_with_sources(
        self,
        state: AgentState,
        *,
        token_budget: int | None = None,
    ) -> tuple[list[dict[str, str]], _ContextAssembly]:
        system_content = self._generation_system_content()
        user_content_factory = lambda context: (
                f"質問: {state['question']}\n\n"
                f"{self._generation_route_note(state)}"
                f"{self._generation_location_fact(state)}"
                "利用可能な根拠:\n"
                f"{context}\n\n"
                f"{self._generation_investigation_log_line(state)}"
                "上の根拠だけに基づいて回答してください。"
        )
        history_messages, context_budget = self._generation_history_and_context_budget(
            state.get("history", []),
            system_content,
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
                system_content,
                history_messages,
                user_content_factory,
                full_context.text,
            )
            if self._fits_prompt_budget(messages, self.llm_answer_max_tokens):
                return messages, full_context

        return self._build_messages_with_context_budget(
            system_content=system_content,
            user_content_factory=user_content_factory,
            knowledge_results=state.get("knowledge_results") or [],
            web_results=state.get("web_results") or [],
            max_tokens=self.llm_answer_max_tokens,
            context_mode="generate",
            history_messages=history_messages,
            context_token_budget=context_budget,
        )

    def _generation_system_content(self) -> str:
        # The time-context block is injected into the system prompt so token
        # budgeting (estimate_tokens over composed messages) accounts for it.
        return f"{GENERATE_SYSTEM_PROMPT}\n\n時間コンテキスト:\n{self.time_context_provider()}"

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
    def _generation_route_note(state: AgentState) -> str:
        origin = state.get("route_origin")
        if origin is None or not state.get("route_origin_from_history"):
            return ""
        return f"経路の出発地（直前の会話から継承）: {origin.label}\n\n"

    @staticmethod
    def _generation_location_fact(state: AgentState) -> str:
        destination = state.get("route_destination")
        if destination is None:
            return ""
        resolved_name = destination.resolved_name or destination.room or destination.label
        room = f"{destination.room} — " if destination.room else ""
        floor = f" / {destination.floor}階" if destination.floor is not None else ""
        return (
            "【位置データ（オープンキャンパス2026 会場・場所インデックスより）】"
            f"{resolved_name}: {room}{destination.label}{floor}。"
            "階の記載がない部屋は棟までが確定情報。\n\n"
        )

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
                body = self._center_excerpt_on_keywords(body, chunk.grep_keywords, limit=EVALUATE_CONTEXT_CHARS)
            else:
                body = body[:EVALUATE_CONTEXT_CHARS]
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
            body = body[:EVALUATE_CONTEXT_CHARS]
            body_label = "summary"
        return self._fit_context_item(
            [
                f"[web:{index}] {result.title}",
                f"url: {result.url}",
                f"snippet: {result.snippet[:EVALUATE_CONTEXT_CHARS]}",
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
        additional_sources: Sequence[Source] = (),
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
        for source in additional_sources:
            key = (source.type, source.url)
            if key in seen:
                continue
            seen.add(key)
            sources.append(source)
        return sources

    def _assemble_generation_sources(
        self,
        state: AgentState,
        context: _ContextAssembly | None,
    ) -> list[Source]:
        knowledge_results = context.knowledge_results if context is not None else []
        web_results = context.web_results if context is not None else []
        location_sources = [LOCATION_INDEX_SOURCE] if state.get("route_destination") is not None else []
        return self._assemble_sources(knowledge_results, web_results, location_sources)

    @staticmethod
    def _generation_context_trace(state: AgentState, context: _ContextAssembly) -> dict[str, list[str]]:
        adopted_chunk_ids = [chunk.id for chunk in context.knowledge_results]
        adopted_chunk_id_set = set(adopted_chunk_ids)
        rejected_chunk_ids = [
            chunk.id
            for chunk in state.get("knowledge_results", [])
            if chunk.id not in adopted_chunk_id_set
        ]
        return {
            "generation_adopted_chunk_ids": adopted_chunk_ids,
            "generation_rejected_chunk_ids": rejected_chunk_ids,
            "generation_adopted_web_urls": [result.url for result in context.web_results],
        }

    @staticmethod
    def _trace_chunk_hit(chunk: KnowledgeChunk) -> dict[str, Any]:
        return {
            "file_id": chunk.file_id,
            "chunk_index": chunk.chunk_index,
            "score": chunk.score,
        }

    @staticmethod
    def _trace_enabled() -> bool:
        return os.getenv("AGENT_TRACE", "1").strip() != "0"

    def _trace(self, event: str, state: AgentState, payload: dict[str, Any]) -> None:
        if not self._trace_enabled():
            return
        record = {
            "event": event,
            "trace_id": state.get("trace_id"),
            **payload,
        }
        trace_logger.info(json.dumps(record, ensure_ascii=False, separators=(",", ":")))

    async def _fetch_search_results(
        self,
        results: Sequence[WebSearchResult],
        *,
        keywords: Sequence[str],
        fetch_missing: bool = True,
    ) -> list[WebSearchResult]:
        fetched: list[WebSearchResult] = []
        for result in results:
            if result.text.strip():
                text = self._focus_page_text(result.text, keywords)
            elif fetch_missing:
                try:
                    text = await self._fetch_page_text(result.url, keywords=keywords)
                except Exception:
                    continue
            else:
                text = result.snippet.strip()
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
        return " ".join(root.get_text(" ", strip=True).split())
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

    def _knowledge_duplicate_summary(
        self,
        existing_results: Sequence[KnowledgeChunk],
        new_results: Sequence[KnowledgeChunk],
    ) -> _KnowledgeDuplicateSummary:
        seen_ids = {chunk.id for chunk in existing_results}
        duplicate_count = 0
        duplicate_file_ids: list[str] = []
        for chunk in new_results:
            if chunk.id in seen_ids:
                duplicate_count += 1
                if chunk.file_id:
                    duplicate_file_ids.append(chunk.file_id)
                continue
            seen_ids.add(chunk.id)
        return _KnowledgeDuplicateSummary(
            count=duplicate_count,
            file_ids=self._dedupe_keys(duplicate_file_ids),
        )

    def _knowledge_observation_file_ids(
        self,
        chunks: Sequence[KnowledgeChunk],
        duplicate_file_ids: Sequence[str],
    ) -> list[str]:
        return self._dedupe_keys(
            [
                *(chunk.file_id or "" for chunk in chunks[:3]),
                *duplicate_file_ids,
            ]
        )

    def _known_file_ids(self, state: AgentState) -> list[str]:
        return self._dedupe_keys(state.get("known_file_ids") or [])

    def _merge_known_file_ids(
        self,
        state: AgentState,
        additions: Sequence[str],
    ) -> list[str]:
        return self._dedupe_keys([*self._known_file_ids(state), *additions])

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

    def _merge_and_expand_knowledge_results(
        self,
        state: AgentState,
        existing_results: Sequence[KnowledgeChunk],
        new_results: Sequence[KnowledgeChunk],
    ) -> _KnowledgeMergeOutcome:
        merged = self._merge_knowledge_results(existing_results, new_results)
        return self._expand_same_file_chunks(state, merged)

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
                same_file_expanded=current.same_file_expanded and chunk.same_file_expanded,
                score=self._merged_score(current, chunk),
            )

        return self._ordered_knowledge_results(by_id.values())

    def _expand_same_file_chunks(
        self,
        state: AgentState,
        merged_results: Sequence[KnowledgeChunk],
    ) -> _KnowledgeMergeOutcome:
        inferred_expanded_file_ids = [
            chunk.file_id for chunk in merged_results if chunk.same_file_expanded and chunk.file_id
        ]
        inferred_expanded_chunk_ids = [chunk.id for chunk in merged_results if chunk.same_file_expanded]
        expanded_file_ids = self._dedupe_keys(
            [*(state.get("same_file_expanded_file_ids") or []), *inferred_expanded_file_ids]
        )
        expanded_chunk_ids = self._dedupe_keys(
            [*(state.get("same_file_expanded_chunk_ids") or []), *inferred_expanded_chunk_ids]
        )
        expanded_file_id_set = set(expanded_file_ids)

        if self.lexical_search is None:
            return _KnowledgeMergeOutcome(
                results=list(merged_results)[:MAX_KNOWLEDGE_CONTEXT_CHUNKS],
                expanded_file_ids=expanded_file_ids,
                expanded_chunk_ids=expanded_chunk_ids,
            )

        load_sections = getattr(self.lexical_search, "_load_sections", None)
        if not callable(load_sections):
            return _KnowledgeMergeOutcome(
                results=list(merged_results)[:MAX_KNOWLEDGE_CONTEXT_CHUNKS],
                expanded_file_ids=expanded_file_ids,
                expanded_chunk_ids=expanded_chunk_ids,
            )

        direct_results = self._ordered_knowledge_results(
            [chunk for chunk in merged_results if not chunk.same_file_expanded]
        )
        selected_direct = direct_results[:MAX_KNOWLEDGE_CONTEXT_CHUNKS]
        remaining_slots = MAX_KNOWLEDGE_CONTEXT_CHUNKS - len(selected_direct)
        if remaining_slots <= 0:
            return _KnowledgeMergeOutcome(
                results=selected_direct,
                expanded_file_ids=expanded_file_ids,
                expanded_chunk_ids=expanded_chunk_ids,
            )

        previous_expansions = [chunk for chunk in merged_results if chunk.same_file_expanded]
        sections = load_sections()
        existing_ids = {chunk.id for chunk in merged_results}
        new_expansions: list[KnowledgeChunk] = []
        new_expansion_file_by_id: dict[str, str] = {}
        for file_id, candidates in self._same_file_expansion_candidates(
            selected_direct,
            sections,
            existing_ids,
            expanded_file_id_set,
        ):
            for chunk in candidates:
                new_expansions.append(chunk)
                new_expansion_file_by_id[chunk.id] = file_id

        selected_expansions = self._merge_knowledge_results(previous_expansions, new_expansions)[:remaining_slots]
        selected_new_by_file: dict[str, list[KnowledgeChunk]] = {}
        for chunk in selected_expansions:
            file_id = new_expansion_file_by_id.get(chunk.id)
            if file_id is None:
                continue
            selected_new_by_file.setdefault(file_id, []).append(chunk)

        for file_id, selected in selected_new_by_file.items():
            expanded_file_id_set.add(file_id)
            expanded_file_ids.append(file_id)
            expanded_chunk_ids.extend(chunk.id for chunk in selected)
            self._trace(
                "expand",
                state,
                {
                    "file_id": file_id,
                    "added_chunk_indices": [
                        chunk.chunk_index for chunk in selected if chunk.chunk_index is not None
                    ],
                },
            )

        return _KnowledgeMergeOutcome(
            results=self._merge_knowledge_results(selected_direct, selected_expansions)[
                :MAX_KNOWLEDGE_CONTEXT_CHUNKS
            ],
            expanded_file_ids=self._dedupe_keys(expanded_file_ids),
            expanded_chunk_ids=self._dedupe_keys(expanded_chunk_ids),
        )

    def _same_file_expansion_candidates(
        self,
        direct_results: Sequence[KnowledgeChunk],
        sections: Sequence[Any],
        existing_ids: set[str],
        expanded_file_ids: set[str],
    ) -> list[tuple[str, list[KnowledgeChunk]]]:
        direct_by_file: dict[str, list[KnowledgeChunk]] = {}
        for chunk in direct_results:
            if not chunk.file_id:
                continue
            direct_by_file.setdefault(chunk.file_id, []).append(chunk)

        sections_by_file: dict[str, list[KnowledgeChunk]] = {}
        for section in sections:
            chunk = getattr(section, "chunk", None)
            if chunk is None or not chunk.file_id:
                continue
            sections_by_file.setdefault(chunk.file_id, []).append(chunk)

        expansion_groups: list[tuple[str, list[KnowledgeChunk]]] = []
        for file_id, direct_chunks in direct_by_file.items():
            if file_id in expanded_file_ids or len(direct_chunks) < 2:
                continue

            scores = [chunk.score for chunk in direct_chunks if chunk.score is not None]
            if not scores:
                continue

            expansion_score = min(scores) - 0.01
            candidates = [
                replace(
                    chunk,
                    score=expansion_score,
                    grep_hit=False,
                    grep_keywords=(),
                    same_file_expanded=True,
                )
                for chunk in sorted(
                    sections_by_file.get(file_id, []),
                    key=lambda item: (
                        item.chunk_index is None,
                        item.chunk_index if item.chunk_index is not None else 0,
                        item.id,
                    ),
                )
                if chunk.id not in existing_ids
            ][:MAX_SAME_FILE_EXPANSION_CHUNKS]
            if candidates:
                expansion_groups.append((file_id, candidates))

        return expansion_groups

    def _generation_investigation_log_line(self, state: AgentState) -> str:
        log = state.get("actions_log") or []
        if not log:
            return ""
        details = [
            f"{item.get('action')}: {item.get('result')}"
            for item in log
            if item.get("action") not in {"finish", "ask_user"}
        ]
        return f"調査ログ: {' / '.join(details)}\n\n" if details else ""
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
