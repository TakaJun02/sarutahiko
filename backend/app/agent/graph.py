from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from datetime import date
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from app.models.auth import User
from app.models.chat import DonePayload, Source, StatusPayload, TokenPayload
from app.rag.models import KnowledgeChunk
from app.search.models import WebSearchResult

Step = Literal["analyze", "retrieve", "web_search", "evaluate", "generate"]

STATUS_TEXTS: dict[Step, str] = {
    "analyze": "質問の意図を整理しています…",
    "retrieve": "学内ナレッジを検索しています…",
    "evaluate": "情報が十分か確認しています…",
    "web_search": "Webで最新情報を確認しています…",
    "generate": "回答をまとめています…",
}


class AgentState(TypedDict, total=False):
    question: str
    role: str
    history: list[dict]
    retrieval_query: str
    needs_external: bool
    knowledge_results: list[KnowledgeChunk]
    web_results: list[WebSearchResult]
    sufficient: bool
    generation_messages: list[dict[str, str]]
    sources: list[Source]


class RealCampusAgent:
    def __init__(
        self,
        *,
        llm_client: Any,
        knowledge_store: Any,
        search_provider: Any,
        top_k: int = 6,
        min_relevance_score: float = 0.45,
    ) -> None:
        self.llm_client = llm_client
        self.knowledge_store = knowledge_store
        self.search_provider = search_provider
        self.top_k = top_k
        self.min_relevance_score = min_relevance_score
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
            "history": (history or [])[-6:],
            "knowledge_results": [],
            "web_results": [],
        }

        yield "status", self._status("analyze")
        async for update in self._graph.astream(state, stream_mode="updates"):
            for node_name, partial in update.items():
                if node_name == END:
                    continue
                if isinstance(partial, dict):
                    state.update(partial)
                next_step = self._next_step_after(node_name, state)
                if next_step:
                    yield "status", self._status(next_step)

        messages = state.get("generation_messages") or self._build_generation_messages(state)
        async for token in self.llm_client.stream_chat(messages, enable_thinking=False):
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
        workflow.add_edge("web_search", "generate")
        workflow.add_edge("generate", END)
        return workflow.compile()

    async def _analyze(self, state: AgentState) -> dict:
        question = state["question"]
        return {
            "retrieval_query": self._build_retrieval_query(question),
            "needs_external": self._needs_current_or_external_info(question),
        }

    async def _retrieve(self, state: AgentState) -> dict:
        results = await self.knowledge_store.search(state["retrieval_query"], limit=self.top_k)
        return {"knowledge_results": results}

    async def _evaluate(self, state: AgentState) -> dict:
        return {"sufficient": self._has_sufficient_knowledge(state.get("knowledge_results", []))}

    async def _web_search(self, state: AgentState) -> dict:
        query = f"{state['question']} 秋田県立大学 本荘キャンパス"
        results = await self.search_provider.search(query, max_results=3)
        return {"web_results": results}

    async def _prepare_generation(self, state: AgentState) -> dict:
        sources = self._assemble_sources(
            state.get("knowledge_results") or [],
            state.get("web_results") or [],
        )
        return {
            "generation_messages": self._build_generation_messages(state),
            "sources": sources,
        }

    def _route_after_evaluate(self, state: AgentState) -> str:
        if not state.get("sufficient", False) and state.get("needs_external", False):
            return "web_search"
        return "generate"

    def _next_step_after(self, node_name: str, state: AgentState) -> Step | None:
        if node_name == "analyze":
            return "retrieve"
        if node_name == "retrieve":
            return "evaluate"
        if node_name == "evaluate":
            return "web_search" if self._route_after_evaluate(state) == "web_search" else "generate"
        if node_name == "web_search":
            return "generate"
        return None

    @staticmethod
    def _status(step: Step) -> dict:
        return StatusPayload(step=step, text=STATUS_TEXTS[step]).model_dump()

    @staticmethod
    def _build_retrieval_query(question: str) -> str:
        # Every document is campus-scoped already; appending the campus name
        # inflates similarity for unrelated questions and drowns discrimination
        # (measured 2026-07-11: unrelated queries scored ~0.6 with the suffix
        # vs ~0.38 without, while relevant answers stay >= 0.58).
        return question.strip()

    @staticmethod
    def _needs_current_or_external_info(question: str) -> bool:
        terms = (
            "最新",
            "現在",
            "今日",
            "明日",
            "今年",
            "2026",
            "令和8",
            "日程",
            "時刻",
            "時刻表",
            "予約",
            "申込",
            "変更",
            "中止",
            "開催",
            "天気",
            "バス",
            "運休",
            "交通",
            "オープンキャンパス",
        )
        return any(term in question for term in terms)

    def _has_sufficient_knowledge(self, results: Sequence[KnowledgeChunk]) -> bool:
        if not results:
            return False
        top_score = results[0].score
        if top_score is not None and top_score < self.min_relevance_score:
            return False
        return any(chunk.text.strip() and chunk.confidence != "low" for chunk in results)

    def _build_generation_messages(self, state: AgentState) -> list[dict[str, str]]:
        system_prompt = self._system_prompt(role=state.get("role", "other"))
        context = self._format_context(
            state.get("knowledge_results") or [],
            state.get("web_results") or [],
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        messages.extend(self._format_history(state.get("history", [])))
        messages.append(
            {
                "role": "user",
                "content": (
                    f"現在日付: {date.today().isoformat()}\n"
                    f"質問: {state['question']}\n\n"
                    "利用可能な根拠:\n"
                    f"{context}\n\n"
                    "上の根拠だけに基づいて回答してください。"
                ),
            }
        )
        return messages

    @staticmethod
    def _system_prompt(role: str) -> str:
        role_instruction = {
            "highschool": "高校生にも分かりやすい語彙で、親しみやすく丁寧に答えてください。",
            "parent": "保護者が確認しやすいように、要点と注意点を整理して答えてください。",
            "other": "来場者に向けて、必要な情報を簡潔かつ丁寧に答えてください。",
        }.get(role, "来場者に向けて、必要な情報を簡潔かつ丁寧に答えてください。")
        return (
            "あなたは秋田県立大学 本荘キャンパスのオープンキャンパス2026来場者向け案内AIです。\n"
            f"{role_instruction}\n"
            "回答は日本語で、丁寧でフレンドリーな文体にしてください。\n"
            "学内ナレッジまたはWeb検索結果として提示された根拠だけを使い、根拠にない内容やURLを作らないでください。\n"
            "根拠が足りない場合は、分からないと明確に伝え、秋田県立大学の公式サイトで確認するよう案内してください。\n"
            "年度に依存する情報は、根拠にある年度または現在の年を明記してください。"
        )

    @staticmethod
    def _format_history(history: Sequence[dict]) -> list[dict[str, str]]:
        formatted: list[dict[str, str]] = []
        for message in history[-6:]:
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = str(message.get("content", "")).strip()
            if content:
                formatted.append({"role": role, "content": content[:2000]})
        return formatted

    @staticmethod
    def _format_context(
        knowledge_results: Sequence[KnowledgeChunk],
        web_results: Sequence[WebSearchResult],
    ) -> str:
        lines: list[str] = []
        for index, chunk in enumerate(knowledge_results, start=1):
            source_urls = ", ".join(chunk.source_urls)
            lines.append(
                "\n".join(
                    [
                        f"[knowledge:{index}] {chunk.title}",
                        f"category: {chunk.category}",
                        f"confidence: {chunk.confidence}",
                        f"source_urls: {source_urls}",
                        f"text: {chunk.text}",
                    ]
                )
            )
        for index, result in enumerate(web_results, start=1):
            lines.append(
                "\n".join(
                    [
                        f"[web:{index}] {result.title}",
                        f"url: {result.url}",
                        f"snippet: {result.snippet}",
                    ]
                )
            )
        return "\n\n".join(lines) if lines else "利用できる根拠はありません。"

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
