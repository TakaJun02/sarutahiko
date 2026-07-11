from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from typing import Any, Literal, TypedDict

import httpx
from langgraph.graph import END, StateGraph
from openai import BadRequestError

from app.models.auth import User
from app.models.chat import DonePayload, Source, StatusPayload, TokenPayload
from app.rag.models import KnowledgeChunk
from app.search.models import WebSearchResult

Step = Literal["analyze", "retrieve", "web_search", "evaluate", "generate"]

MAX_RETRIEVAL_QUERIES = 3
MAX_KNOWLEDGE_CONTEXT_CHUNKS = 10
MAX_WEB_SEARCH_ROUNDS = 2
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

STATUS_TEXTS: dict[Step, str] = {
    "analyze": "質問の意図を整理しています…",
    "retrieve": "学内ナレッジを検索しています…",
    "evaluate": "情報が十分か確認しています…",
    "web_search": "Webで最新情報を確認しています…",
    "generate": "回答をまとめています…",
}

FOLLOWUP_STATUS_TEXTS: dict[Step, str] = {
    "evaluate": "集めた情報を検証しています…",
    "web_search": "別の観点でWebを調べています…",
}

GENERATE_SYSTEM_PROMPT = """あなたは秋田県立大学 本荘キャンパスのオープンキャンパス2026来場者向け案内AIです。
回答は日本語で、丁寧でフレンドリーな文体にしてください。
利用者ロール別のトーンは次を守ってください。highschool: 高校生にも分かりやすい語彙で、親しみやすく丁寧に答える。parent: 保護者が確認しやすいように、要点と注意点を整理して答える。other: 来場者に向けて、必要な情報を簡潔かつ丁寧に答える。

回答ルール:
1. 禁止: 「公式サイトでご確認ください」「当日の学科紹介でご確認いただけます」など、調べれば答えられる内容を利用者に丸投げする表現を回答の主内容にしないでください。
2. コンテキストにある情報は、数字・固有名詞・手順まで具体的に盛り込み、省略しないでください。
3. 検索を尽くしても根拠がない場合のみ「現時点で確認できなかった」と正直に述べ、何をどこまで調べたか（学内ナレッジ・大学公式サイトのWeb検索）を一言添えてください。その場合に限り、補助情報として問い合わせ先を案内して構いません。
4. 年度依存情報は年度を明記し、根拠にない内容やURLを捏造しないでください。"""


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
    knowledge_results: list[KnowledgeChunk]
    web_results: list[WebSearchResult]
    sufficient: bool
    missing: str
    web_queries: list[str]
    web_search_rounds: int
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


class RealCampusAgent:
    def __init__(
        self,
        *,
        llm_client: Any,
        knowledge_store: Any,
        search_provider: Any,
        top_k: int = 6,
        min_relevance_score: float = 0.45,
        http_client_factory: Callable[[], Any] | None = None,
        llm_context_window: int = DEFAULT_LLM_CONTEXT_WINDOW,
        llm_answer_max_tokens: int = DEFAULT_LLM_ANSWER_MAX_TOKENS,
    ) -> None:
        self.llm_client = llm_client
        self.knowledge_store = knowledge_store
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
        }

        yield "status", self._status("analyze", state)
        state.update(await self._analyze(state))

        yield "status", self._status("retrieve", state)
        state.update(await self._retrieve(state))

        yield "status", self._status("evaluate", state)
        state.update(await self._evaluate(state))

        while self._route_after_evaluate(state) == "web_search":
            yield "status", self._status("web_search", state)
            state.update(await self._web_search(state))

            yield "status", self._status("evaluate", state)
            state.update(await self._evaluate(state))

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
        workflow.add_node("evaluate", self._evaluate)
        workflow.add_node("web_search", self._web_search)
        workflow.add_node("evaluate_after_web", self._evaluate_after_web)
        workflow.add_node("web_search_second", self._web_search_second)
        workflow.add_node("evaluate_after_second", self._evaluate_after_second)
        workflow.add_node("generate", self._prepare_generation)
        workflow.set_entry_point("analyze")
        workflow.add_edge("analyze", "retrieve")
        workflow.add_edge("retrieve", "evaluate")
        workflow.add_conditional_edges(
            "evaluate",
            self._route_after_evaluate,
            {
                "web_search": "web_search",
                "generate": "generate",
            },
        )
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
        return {"retrieval_queries": queries}

    async def _retrieve(self, state: AgentState) -> dict:
        by_id: dict[str, KnowledgeChunk] = {}
        for query in state.get("retrieval_queries") or [state["question"]]:
            results = await self.knowledge_store.search(query, limit=self.top_k)
            for chunk in results:
                if self._is_below_relevance_floor(chunk):
                    continue
                current = by_id.get(chunk.id)
                if current is None or self._score_value(chunk) > self._score_value(current):
                    by_id[chunk.id] = chunk

        merged = sorted(by_id.values(), key=self._score_value, reverse=True)
        return {"knowledge_results": merged[:MAX_KNOWLEDGE_CONTEXT_CHUNKS]}

    async def _evaluate(self, state: AgentState) -> dict:
        raw_output = await self.llm_client.complete_chat(
            self._build_evaluate_messages(state),
            temperature=0.2,
            max_tokens=EVALUATE_MAX_TOKENS,
            enable_thinking=False,
        )
        payload = self._parse_json_object(raw_output)
        if payload is None:
            return {"sufficient": True, "missing": "", "web_queries": []}

        sufficient = self._parse_bool(payload.get("sufficient"), default=True)
        web_queries = self._normalize_queries(
            payload.get("web_queries"),
            fallback=[state["question"]] if not sufficient else [],
            limit=MAX_RETRIEVAL_QUERIES,
        )
        return {
            "sufficient": sufficient,
            "missing": str(payload.get("missing") or ""),
            "web_queries": web_queries,
        }

    async def _evaluate_after_web(self, state: AgentState) -> dict:
        return await self._evaluate(state)

    async def _evaluate_after_second(self, state: AgentState) -> dict:
        return await self._evaluate(state)

    async def _web_search(self, state: AgentState) -> dict:
        round_number = state.get("web_search_rounds", 0) + 1
        queries = state.get("web_queries") or [state["question"]]
        candidates = await self._search_web_round(
            queries=queries,
            round_number=round_number,
            existing_urls={result.url for result in state.get("web_results", [])},
        )
        fetched_results = await self._fetch_search_results(candidates[:MAX_WEB_PAGES_PER_ROUND])
        web_results = self._dedupe_web_results([*(state.get("web_results") or []), *fetched_results])
        return {
            "web_results": web_results,
            "web_search_rounds": round_number,
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
        if not state.get("sufficient", True) and state.get("web_search_rounds", 0) < MAX_WEB_SEARCH_ROUNDS:
            return "web_search"
        return "generate"

    def _route_after_first_web_evaluate(self, state: AgentState) -> str:
        if not state.get("sufficient", True) and state.get("web_search_rounds", 0) < MAX_WEB_SEARCH_ROUNDS:
            return "web_search_second"
        return "generate"

    def _next_step_after(self, node_name: str, state: AgentState) -> Step | None:
        if node_name == "analyze":
            return "retrieve"
        if node_name == "retrieve":
            return "evaluate"
        if node_name == "evaluate":
            return "web_search" if self._route_after_evaluate(state) == "web_search" else "generate"
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
        web_rounds = (state or {}).get("web_search_rounds", 0)
        text = FOLLOWUP_STATUS_TEXTS.get(step, STATUS_TEXTS[step]) if web_rounds >= 1 else STATUS_TEXTS[step]
        return StatusPayload(step=step, text=text).model_dump()

    def _build_analyze_messages(self, question: str, history: Sequence[dict]) -> list[dict[str, str]]:
        history_text = RealCampusAgent._format_history_for_prompt(history)
        messages = self._raw_analyze_messages(question, history_text)
        if self._fits_prompt_budget(messages, ANALYZE_MAX_TOKENS):
            return messages

        messages = self._raw_analyze_messages(question, "なし")
        if self._fits_prompt_budget(messages, ANALYZE_MAX_TOKENS):
            return messages
        return self._truncate_last_user_message(messages, ANALYZE_MAX_TOKENS)

    @staticmethod
    def _raw_analyze_messages(question: str, history_text: str) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "あなたは秋田県立大学 本荘キャンパス案内AIの検索計画担当です。"
                    "質問と直近履歴から、学内ナレッジ検索に使う観点違いの検索クエリを2〜3本作ってください。"
                    "出力はJSONのみで、形式は {\"retrieval_queries\": [\"...\", \"...\"], \"intent\": \"...\"} です。"
                ),
            },
            {
                "role": "user",
                "content": f"直近履歴:\n{history_text}\n\n質問:\n{question}",
            },
        ]

    def _build_evaluate_messages(self, state: AgentState) -> list[dict[str, str]]:
        messages, _ = self._build_budgeted_context_messages(
            system_content=(
                "あなたは秋田県立大学 本荘キャンパス案内AIの根拠評価担当です。"
                "来場者に具体的な回答（数字・固有名詞・手順）を返せるかを判定してください。"
                "一般論しか言えない、重要な詳細が欠ける、根拠が曖昧な場合は insufficient としてください。"
                "出力はJSONのみで、形式は {\"sufficient\": true|false, \"missing\": \"...\", \"web_queries\": [\"...\", \"...\"]} です。"
                "不足時のweb_queriesは、追加Web検索で使う短い日本語クエリにしてください。"
            ),
            user_content_factory=lambda context: (
                f"質問: {state['question']}\n\n"
                f"現在のコンテキスト:\n{context}"
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
        return self._build_budgeted_context_messages(
            system_content=GENERATE_SYSTEM_PROMPT,
            user_content_factory=lambda context: (
                f"利用者ロール: {state.get('role', 'other')}\n"
                f"現在日付: {date.today().isoformat()}\n"
                f"質問: {state['question']}\n\n"
                "利用可能な根拠:\n"
                f"{context}\n\n"
                "上の根拠だけに基づいて回答してください。"
            ),
            knowledge_results=state.get("knowledge_results") or [],
            web_results=state.get("web_results") or [],
            max_tokens=self.llm_answer_max_tokens,
            context_mode="generate",
            history_messages=self._format_history(state.get("history", [])),
            context_token_budget=token_budget,
        )

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

        if active_history:
            active_history = []
            messages = self._compose_context_messages(
                system_content,
                active_history,
                user_content_factory,
                full_context.text,
            )
            if self._fits_prompt_budget(messages, max_tokens):
                return messages, full_context

        base_messages = self._compose_context_messages(system_content, active_history, user_content_factory, "")
        context_budget = max(self._prompt_budget(max_tokens) - self._estimate_messages(base_messages), 0)
        context = self._assemble_context_with_budget(
            knowledge_results,
            web_results,
            mode=context_mode,
            token_budget=context_budget,
        )
        messages = self._compose_context_messages(system_content, active_history, user_content_factory, context.text)
        if self._fits_prompt_budget(messages, max_tokens):
            return messages, context
        return self._truncate_last_user_message(messages, max_tokens), context

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
        context = self._assemble_context_with_budget(
            knowledge_results,
            web_results,
            mode=context_mode,
            token_budget=context_token_budget,
        )
        messages = self._compose_context_messages(system_content, history_messages, user_content_factory, context.text)
        if self._fits_prompt_budget(messages, max_tokens):
            return messages, context

        messages = self._compose_context_messages(system_content, [], user_content_factory, context.text)
        if self._fits_prompt_budget(messages, max_tokens):
            return messages, context
        return self._truncate_last_user_message(messages, max_tokens), context

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
    def _format_history(history: Sequence[dict]) -> list[dict[str, str]]:
        formatted: list[dict[str, str]] = []
        for message in history[-MAX_HISTORY_MESSAGES:]:
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = str(message.get("content", "")).strip()
            if content:
                formatted.append({"role": role, "content": content[:MAX_HISTORY_CHARS]})
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

        def add_knowledge() -> None:
            for index, chunk in enumerate(self._ordered_knowledge_results(knowledge_results), start=1):
                added = self._append_context_item(
                    parts,
                    lambda available_tokens, chunk=chunk, index=index: self._fit_knowledge_context_item(
                        chunk,
                        index,
                        mode=mode,
                        available_tokens=available_tokens,
                    ),
                    token_budget=token_budget,
                )
                if added:
                    included_knowledge.append(chunk)

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

        # Web results exist only when the knowledge evaluation judged the local
        # context insufficient, so under budget pressure they must win over
        # lower-value knowledge chunks — otherwise the whole web_search round
        # gets silently truncated away.
        if web_results:
            add_web()
            add_knowledge()
        else:
            add_knowledge()

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
            body = body[:400]
            body_label = "summary"
        return self._fit_context_item(
            [
                f"[knowledge:{index}] {chunk.title}",
                f"category: {chunk.category}",
                f"confidence: {chunk.confidence}",
                f"score: {chunk.score}",
                f"source_urls: {source_urls}",
            ],
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
        queries: Sequence[str],
        round_number: int,
        existing_urls: set[str],
    ) -> list[WebSearchResult]:
        results: list[WebSearchResult] = []
        seen_urls = set(existing_urls)
        for query in queries:
            if len(results) >= MAX_WEB_RESULTS_PER_ROUND:
                break
            search_query = f"site:akita-pu.ac.jp {query}" if round_number == 1 else query
            rows = await self.search_provider.search(
                search_query,
                max_results=MAX_WEB_RESULTS_PER_ROUND - len(results),
            )
            for result in rows:
                if result.url in seen_urls:
                    continue
                seen_urls.add(result.url)
                results.append(result)
                if len(results) >= MAX_WEB_RESULTS_PER_ROUND:
                    break
        return results

    async def _fetch_search_results(self, results: Sequence[WebSearchResult]) -> list[WebSearchResult]:
        fetched: list[WebSearchResult] = []
        for result in results:
            try:
                text = await self._fetch_page_text(result.url)
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

    async def _fetch_page_text(self, url: str) -> str:
        async with self.http_client_factory() as client:
            response = await client.get(url)
            response.raise_for_status()
        return self._extract_main_text(response.text)

    @staticmethod
    def _extract_main_text(html: str) -> str:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            parser = _FallbackTextExtractor()
            parser.feed(html)
            return parser.text[:MAX_WEB_PAGE_CHARS]

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()
        root = soup.find("main") or soup.body or soup
        text = " ".join(root.get_text(" ", strip=True).split())
        return text[:MAX_WEB_PAGE_CHARS]

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
    def _default_http_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=8.0, follow_redirects=True)
