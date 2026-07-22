from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from typing import Any

from app.agent.campus_map import (
    ResolvedLocation,
    build_ask_origin_map_payload,
    build_place_map_payload,
    build_route_map_payload,
    find_locations_in_text,
    resolve_location,
)
from app.agent.thought_stream import ThoughtStreamExtractor
from app.models.chat import Source

NAVIGATOR_MAX_STEPS = 3
NAVIGATOR_ACTIONS = ("resolve_place", "find_route", "ask_origin")
ASK_ORIGIN_RESPONSE = (
    "いまいる場所をマップでタップして教えてください！"
    "そこからの行き方をご案内します🗺️"
)
LOCATION_INDEX_SOURCE = Source(
    title="オープンキャンパス2026 会場・場所インデックス（どこ・何階・何号室）",
    url=(
        "https://www.akita-pu.ac.jp/up/files/www/oshirase/oshirase2026/"
        "OC2026%E3%82%BF%E3%82%A4%E3%83%A0%E3%83%86%E3%83%BC%E3%83%96%E3%83%AB.pdf"
    ),
    type="knowledge",
)

NAVIGATOR_SYSTEM_PROMPT = """あなたは秋田県立大学 本荘キャンパス（秋田県由利本荘市）の学内場所・経路を扱う campus_navigator です。
本学を「APU」と略さず、他大学と混同しないでください。空間推論や道順の創作はせず、必ず決定的ツールを使います。
JSON {thought, action, action_input} のみを返し、来場者向けの最終文章は書かないでください。

内部ツール:
- resolve_place {expression: string, role: "origin"|"destination"}: 名称を場所データで解決する
- find_route {origin: string, destination: string}: 解決済み両端の決定的経路を求める
- ask_origin {destination: string}: 目的地は解決済みだが出発地が不明な場合だけ現在地選択を提案する

目的地が未解決なら ask_origin を使わず名称を変えて resolve_place してください。出発地が既知なら ask_origin を使わず find_route してください。thought は短い日本語1〜2文です。"""


def navigator_decision_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "thought": {"type": "string"},
            "action": {"type": "string", "enum": list(NAVIGATOR_ACTIONS)},
            "action_input": {"type": "object", "additionalProperties": True},
        },
        "required": ["thought", "action", "action_input"],
        "additionalProperties": False,
    }


class CampusNavigator:
    def __init__(self, llm_client: Any) -> None:
        self.llm_client = llm_client

    async def navigate(
        self,
        *,
        request: str,
        question: str,
        history: Sequence[dict],
        status_callback: Callable[[str, bool], None] | None = None,
    ) -> dict[str, Any]:
        known_origin, origin_from_history = self._known_origin(question, history)
        fast_result = self._fast_path(
            request=request,
            question=question,
            known_origin=known_origin,
            origin_from_history=origin_from_history,
        )
        if fast_result is not None:
            fast_result["fast_path"] = True
            fast_result["trace"] = []
            return fast_result

        intent = self._navigation_intent(request, question)
        resolved_origin = known_origin
        resolved_destination: ResolvedLocation | None = None
        observations: list[str] = []
        trace: list[dict[str, Any]] = []
        for _ in range(NAVIGATOR_MAX_STEPS):
            if status_callback is not None:
                status_callback("キャンパスマップで候補を確認しています…", False)
            messages = self._build_messages(
                request=request,
                question=question,
                history=history,
                known_origin=resolved_origin,
                observations=observations,
            )
            extractor = ThoughtStreamExtractor()
            raw_parts: list[str] = []
            async for fragment in self.llm_client.decide_stream(
                messages,
                navigator_decision_schema(),
            ):
                raw_parts.append(fragment)
                partial_thought = extractor.feed(fragment)
                if partial_thought is not None and status_callback is not None:
                    status_callback(f"{partial_thought}…", True)
            raw = "".join(raw_parts)
            decision = self._parse_decision(raw)
            if decision is None:
                observations.append("JSON 判断を解釈できませんでした。別の内部ツールを選んでください。")
                trace.append({"parse_error": True})
                continue

            thought = str(decision["thought"]).strip()
            action = str(decision["action"])
            action_input = decision["action_input"]
            trace_entry = {"thought": thought, "action": action, "action_input": action_input}

            if action == "resolve_place":
                expression = self._text_input(action_input, "expression")
                role = action_input.get("role")
                resolved = resolve_location(expression)
                if resolved is None:
                    observation = f"場所「{expression}」は解決できませんでした。"
                else:
                    if role == "origin" or (role != "destination" and resolved_destination is not None):
                        resolved_origin = resolved
                        origin_from_history = False
                        observation = f"出発地を {resolved.label} と解決しました。"
                    else:
                        resolved_destination = resolved
                        observation = f"目的地を {self._location_label(resolved)} と解決しました。"
                    if intent == "place" and resolved_destination is not None:
                        trace_entry["observation"] = observation
                        trace.append(trace_entry)
                        result = self._place_result(resolved_destination)
                        result.update({"fast_path": False, "trace": trace})
                        return result
                    if intent == "route" and resolved_origin is not None and resolved_destination is not None:
                        trace_entry["observation"] = observation
                        trace.append(trace_entry)
                        result = self._route_result(
                            resolved_origin,
                            resolved_destination,
                            origin_from_history=origin_from_history,
                        )
                        result.update({"fast_path": False, "trace": trace})
                        return result

            elif action == "find_route":
                origin = resolve_location(self._text_input(action_input, "origin")) or resolved_origin
                destination = (
                    resolve_location(self._text_input(action_input, "destination"))
                    or resolved_destination
                )
                if destination is None:
                    observation = "目的地を特定できません。名称を変えて resolve_place してください。"
                elif origin is None:
                    resolved_destination = destination
                    observation = "出発地が不明です。目的地を指定して ask_origin を検討してください。"
                else:
                    trace_entry["observation"] = "決定的経路を計算しました。"
                    trace.append(trace_entry)
                    result = self._route_result(
                        origin,
                        destination,
                        origin_from_history=origin_from_history,
                    )
                    result.update({"fast_path": False, "trace": trace})
                    return result

            else:  # ask_origin
                destination = (
                    resolve_location(self._text_input(action_input, "destination"))
                    or resolved_destination
                )
                if destination is None:
                    observation = (
                        "目的地を特定できないため ask_origin は実行できません。"
                        "名称を変えて再解決するか not_navigable を検討してください。"
                    )
                elif resolved_origin is not None:
                    observation = (
                        f"出発地は既知です: {resolved_origin.label}。find_route を使ってください。"
                    )
                else:
                    trace_entry["observation"] = "現在地選択の条件を満たしました。"
                    trace.append(trace_entry)
                    result = self._need_origin_result(destination, question)
                    result.update({"fast_path": False, "trace": trace})
                    return result

            trace_entry["observation"] = observation
            trace.append(trace_entry)
            observations.append(observation)

        return {
            "type": "not_navigable",
            "reason": "学内場所データで目的地または経路を確定できませんでした。",
            "fast_path": False,
            "trace": trace,
        }

    def _fast_path(
        self,
        *,
        request: str,
        question: str,
        known_origin: ResolvedLocation | None,
        origin_from_history: bool,
    ) -> dict[str, Any] | None:
        intent = self._navigation_intent(request, question)
        request_locations = [match.location for match in find_locations_in_text(request)]
        question_locations = [match.location for match in find_locations_in_text(question)]
        locations = self._dedupe_locations([*request_locations, *question_locations])
        explicit_origin = self._origin_before_from(question) or self._origin_before_from(request)
        origin = known_origin or explicit_origin
        non_origin_locations = (
            locations
            if origin is None
            else [location for location in locations if location != origin]
        )
        destination_candidates = (
            non_origin_locations
            if non_origin_locations or intent == "route"
            else locations
        )
        destination = self._best_destination(destination_candidates)
        if destination is None:
            return None
        if intent == "place":
            return self._place_result(destination)
        if intent != "route":
            return None
        if origin is None:
            return self._need_origin_result(destination, question)
        return self._route_result(
            origin,
            destination,
            origin_from_history=origin_from_history,
        )

    @staticmethod
    def _navigation_intent(request: str, question: str) -> str | None:
        request_text = request.strip()
        route_markers = ("経路", "行き方", "行きたい", "案内", "移動", "から", "まで")
        place_markers = ("どこ", "場所", "所在", "何号室")
        if any(marker in request_text for marker in route_markers):
            return "route"
        if any(marker in request_text for marker in place_markers):
            return "place"
        if any(marker in question for marker in route_markers):
            return "route"
        if any(marker in question for marker in place_markers):
            return "place"
        return None

    @classmethod
    def _known_origin(
        cls,
        question: str,
        history: Sequence[dict],
    ) -> tuple[ResolvedLocation | None, bool]:
        current = cls._declared_origin(question) or cls._origin_before_from(question)
        if current is not None:
            return current, False
        for message in reversed(history):
            if message.get("role") != "user":
                continue
            map_payload = message.get("map")
            if isinstance(map_payload, dict) and map_payload.get("mode") == "origin_select":
                origin_payload = map_payload.get("origin")
                if isinstance(origin_payload, dict):
                    resolved = resolve_location(str(origin_payload.get("label") or ""))
                    if resolved is not None:
                        return resolved, True
            resolved = cls._declared_origin(str(message.get("content") or ""))
            if resolved is not None:
                return resolved, True
        return None, False

    @staticmethod
    def _declared_origin(text: str) -> ResolvedLocation | None:
        match = re.search(r"現在地は(.+?)です", text)
        return resolve_location(match.group(1).strip()) if match else None

    @staticmethod
    def _origin_before_from(text: str) -> ResolvedLocation | None:
        marker = text.find("から")
        if marker < 0:
            return None
        matches = find_locations_in_text(text[:marker])
        return matches[-1].location if matches else None

    @staticmethod
    def _best_destination(locations: Sequence[ResolvedLocation]) -> ResolvedLocation | None:
        if not locations:
            return None
        return max(
            enumerate(locations),
            key=lambda pair: (
                int(pair[1].room is not None),
                int(pair[1].floor is not None),
                pair[0],
            ),
        )[1]

    @staticmethod
    def _dedupe_locations(locations: Sequence[ResolvedLocation]) -> list[ResolvedLocation]:
        deduped: list[ResolvedLocation] = []
        seen: set[tuple[str, str | None, int | None]] = set()
        for location in locations:
            key = (location.node, location.room, location.floor)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(location)
        return deduped

    @staticmethod
    def _route_result(
        origin: ResolvedLocation,
        destination: ResolvedLocation,
        *,
        origin_from_history: bool,
    ) -> dict[str, Any]:
        payload = build_route_map_payload(origin, destination)
        return {
            "type": "route",
            "origin": origin,
            "destination": destination,
            "origin_from_history": origin_from_history,
            "steps_text": "\n".join(payload.get("steps") or []),
            "map_payload": payload,
            "sources": [LOCATION_INDEX_SOURCE],
        }

    @staticmethod
    def _place_result(destination: ResolvedLocation) -> dict[str, Any]:
        room = f" {destination.room}" if destination.room else ""
        floor = f" {destination.floor}階" if destination.floor is not None else ""
        return {
            "type": "place",
            "destination": destination,
            "fact": f"{destination.label}{room}{floor}".strip(),
            "map_payload": build_place_map_payload(destination),
            "sources": [LOCATION_INDEX_SOURCE],
        }

    @staticmethod
    def _need_origin_result(destination: ResolvedLocation, question: str) -> dict[str, Any]:
        return {
            "type": "need_origin",
            "destination": destination,
            "response": ASK_ORIGIN_RESPONSE,
            "map_payload": build_ask_origin_map_payload(destination, question),
            "sources": [LOCATION_INDEX_SOURCE],
        }

    @staticmethod
    def _location_label(location: ResolvedLocation) -> str:
        return location.room or location.resolved_name or location.label

    @staticmethod
    def _text_input(action_input: dict[str, Any], key: str) -> str:
        value = action_input.get(key)
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _parse_decision(raw: Any) -> dict[str, Any] | None:
        if isinstance(raw, dict):
            value = raw
        else:
            text = str(raw or "").strip()
            candidates = [text]
            start = text.find("{")
            end = text.rfind("}")
            if 0 <= start < end:
                candidates.append(text[start : end + 1])
            value = None
            for candidate in candidates:
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    value = parsed
                    break
            if value is None:
                return None
        if set(value) != {"thought", "action", "action_input"}:
            return None
        if not isinstance(value.get("thought"), str):
            return None
        if value.get("action") not in NAVIGATOR_ACTIONS:
            return None
        if not isinstance(value.get("action_input"), dict):
            return None
        return value

    @staticmethod
    def _build_messages(
        *,
        request: str,
        question: str,
        history: Sequence[dict],
        known_origin: ResolvedLocation | None,
        observations: Sequence[str],
    ) -> list[dict[str, str]]:
        history_lines = [
            f"{message.get('role')}: {str(message.get('content') or '')[:300]}"
            for message in history[-8:]
            if message.get("role") in {"user", "assistant"}
        ]
        origin_line = known_origin.label if known_origin is not None else "不明"
        observation_text = "\n".join(f"- {item}" for item in observations) or "なし"
        return [
            {"role": "system", "content": NAVIGATOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"依頼: {request}\n原質問: {question}\n"
                    f"解決済み出発地: {origin_line}\n"
                    f"直近履歴:\n{chr(10).join(history_lines) or 'なし'}\n"
                    f"内部観測:\n{observation_text}"
                ),
            },
        ]
