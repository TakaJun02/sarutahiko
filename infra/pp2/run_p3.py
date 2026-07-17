#!/usr/bin/env python3
"""P3 decide-quality smoke runner; it deliberately makes no pass/fail decision."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from poc_common import (
    client_from_env,
    decision_schema,
    metadata,
    numeric_summary,
    response_format_for,
    validate_decision,
    write_result_files,
)


ACTIONS = [
    "retrieve",
    "search",
    "web_search",
    "campus_navigator",
    "ask_user",
    "finish",
]

# POC ONLY: Fable is expected to rewrite this decide prompt before FR-34's
# production implementation. It exists solely to exercise P3 mechanics.
POC_DECIDE_SYSTEM_PROMPT = """あなたは APU-Navi の試作 decide コンポーネントです。来場者の質問と
観測を読み、次の action を必ず1つ選び、JSONだけを返してください。

ツール:
- retrieve {queries: string[1..3]}: 意味ベクトルで学内ナレッジを探す
- search {keywords: string[1..6]}: 部屋番号・固有名詞を字句検索する
- web_search {queries: string[1..3]}: ドメイン制限なしで最新情報を探す
- campus_navigator {request: string}: 場所・経路を決定的な経路専門機構へ依頼する
- ask_user {question: string}: 回答が実質的に変わる場合だけ来場者へ聞き返す
- finish {reason: string}: 根拠がそろったら探索を終える

方針:
- ツール実行0回で finish してはいけない。
- 場所の確認や経路は campus_navigator を使い、空間推論を自分でしない。
- 推測で答えられる場合は推測と明示して答える方を優先し、ask_user を乱用しない。
- 同一 action と action_input を繰り返さず、0件ならクエリ変更か別ツールを検討する。
- thought は短い日本語1〜2文にする。
"""

FABLE_QUESTIONS = [
    "受付から D404 への行き方を教えて",
    "図書館はどこにありますか",
    "サイバーフィジカルシステム研究室に行きたい",
    "学食について教えて",
]


def load_category_questions(eval_path: Path) -> list[dict[str, Any]]:
    """Mechanically select the first numbered question from A-I + robustness."""

    selected: dict[str, dict[str, Any]] = {}
    section: str | None = None
    section_pattern = re.compile(r"^## ([A-I])\.\s*(.+)$")
    question_pattern = re.compile(r"^\s*(?:-\s*)?(\d+)\.\s*(.+)$")
    for line in eval_path.read_text(encoding="utf-8").splitlines():
        section_match = section_pattern.match(line)
        if section_match:
            section = f"{section_match.group(1)}. {section_match.group(2)}"
            continue
        if line.startswith("## 頑健性チェック"):
            section = "頑健性チェック"
            continue
        if section is None or section in selected:
            continue
        question_match = question_pattern.match(line)
        if not question_match:
            continue
        question_id = int(question_match.group(1))
        raw = question_match.group(2).strip()
        quoted = re.search(r"「([^」]+)」", raw)
        question = quoted.group(1) if quoted else re.split(r"（→", raw, maxsplit=1)[0]
        selected[section] = {
            "source": "docs/EVAL_QUESTIONS.md",
            "section": section,
            "question_id": question_id,
            "question": question.strip(),
        }

    expected_sections = [
        "A.",
        "B.",
        "C.",
        "D.",
        "E.",
        "F.",
        "G.",
        "H.",
        "I.",
        "頑健性チェック",
    ]
    ordered: list[dict[str, Any]] = []
    for prefix in expected_sections:
        match = next(
            (value for key, value in selected.items() if key.startswith(prefix)), None
        )
        if match is None:
            raise RuntimeError(f"Could not select an evaluation question for {prefix}")
        ordered.append(match)
    return ordered


def mock_observation(validation: dict[str, Any]) -> dict[str, Any]:
    parsed = validation.get("parsed")
    if not validation.get("valid") or not isinstance(parsed, dict):
        return {
            "kind": "parse_error",
            "text": "前の decide 出力を解釈できなかった。正しいJSONで別の行動を選ぶこと。",
        }
    action = parsed["action"]
    if action == "retrieve":
        text = "retrieve の検索結果は0件だった。クエリを変えるか別ツールを検討すること。"
    elif action == "search":
        text = "search の字句検索結果は0件だった。表記を変えるか別ツールを検討すること。"
    elif action == "web_search":
        text = "web_search は0件だった。より具体的なクエリか学内ツールを検討すること。"
    elif action == "campus_navigator":
        text = "campus_navigator は not_navigable を返した。名称を変えるか他の根拠を探すこと。"
    elif action == "finish":
        text = "ツール実行0回の finish は不変条件違反として拒否された。情報を集めること。"
    else:
        text = "ask_user はこのスモークでは終端せず、追加情報なしとして探索継続を求められた。"
    return {"kind": action, "text": text}


def call_decide(client, model: str, messages: list[dict[str, str]], response_format):
    try:
        response = client.chat(
            model=model,
            messages=messages,
            max_tokens=int(os.environ.get("P3_MAX_TOKENS", "300")),
            temperature=float(os.environ.get("P3_TEMPERATURE", "0.2")),
            response_format=response_format,
        )
        return {
            "ok": True,
            **response,
            "schema_validation": validate_decision(response["content"], set(ACTIONS)),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "content": "",
            "schema_validation": {"valid": False, "error": str(exc)},
        }


def main() -> int:
    client = client_from_env()
    available_models = client.list_models()
    model = client.resolve_model(available_models)
    repo_root = Path(__file__).resolve().parents[2]
    questions = load_category_questions(repo_root / "docs" / "EVAL_QUESTIONS.md")
    questions.extend(
        {
            "source": "Fable指定",
            "section": "P3指定ケース",
            "question_id": None,
            "question": question,
        }
        for question in FABLE_QUESTIONS
    )

    schema = decision_schema(ACTIONS)
    guided_format = response_format_for(schema)
    records: list[dict[str, Any]] = []
    for question_info in questions:
        first_messages = [
            {"role": "system", "content": POC_DECIDE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"質問: {question_info['question']}\n"
                    "行動ログ: なし\n観測: なし\nツール実行回数: 0"
                ),
            },
        ]
        first = call_decide(client, model, first_messages, guided_format)
        observation = mock_observation(first["schema_validation"])
        second_messages = [
            *first_messages,
            {"role": "assistant", "content": first.get("content", "")},
            {
                "role": "user",
                "content": f"[MOCK_OBSERVATION]\n{observation['text']}",
            },
        ]
        second = call_decide(client, model, second_messages, guided_format)
        records.append(
            {
                "question": question_info,
                "first_decision": first,
                "mock_observation": observation,
                "second_decision": second,
            }
        )

    first_valid = [
        record["first_decision"]["schema_validation"].get("parsed")
        for record in records
        if record["first_decision"]["schema_validation"].get("valid")
    ]
    repeated = 0
    comparable = 0
    for record in records:
        first_validation = record["first_decision"]["schema_validation"]
        second_validation = record["second_decision"]["schema_validation"]
        if not first_validation.get("valid") or not second_validation.get("valid"):
            continue
        comparable += 1
        first_value = first_validation["parsed"]
        second_value = second_validation["parsed"]
        if (
            first_value["action"] == second_value["action"]
            and first_value["action_input"] == second_value["action_input"]
        ):
            repeated += 1
    finish_first = sum(
        isinstance(value, dict) and value.get("action") == "finish"
        for value in first_valid
    )
    diagnostics = {
        "tool_zero_finish_first_attempt_count": finish_first,
        "tool_zero_finish_first_attempt_rate": (
            finish_first / len(first_valid) if first_valid else None
        ),
        "identical_action_repeat_count": repeated,
        "identical_action_repeat_comparable_count": comparable,
        "identical_action_repeat_rate": repeated / comparable if comparable else None,
        "first_decide_latency_seconds": numeric_summary(
            [
                record["first_decision"]["latency_seconds"]
                for record in records
                if isinstance(
                    record["first_decision"].get("latency_seconds"), (int, float)
                )
            ]
        ),
        "second_decide_latency_seconds": numeric_summary(
            [
                record["second_decision"]["latency_seconds"]
                for record in records
                if isinstance(
                    record["second_decision"].get("latency_seconds"), (int, float)
                )
            ]
        ),
        "two_decide_latency_lower_bound_seconds": numeric_summary(
            [
                record["first_decision"]["latency_seconds"]
                + record["second_decision"]["latency_seconds"]
                for record in records
                if isinstance(
                    record["first_decision"].get("latency_seconds"), (int, float)
                )
                and isinstance(
                    record["second_decision"].get("latency_seconds"), (int, float)
                )
            ]
        ),
    }
    result = {
        "gate": "P3",
        "metadata": metadata(client, model),
        "prompt_status": "PoC trial only; Fable will rewrite for production",
        "system_prompt": POC_DECIDE_SYSTEM_PROMPT,
        "selection_rule": (
            "First numbered question from each EVAL_QUESTIONS section A-I, plus "
            "the first robustness question; then four Fable-specified questions."
        ),
        "schema": schema,
        "diagnostics_without_pass_fail": diagnostics,
        "records": records,
    }

    rows = []
    for index, record in enumerate(records, start=1):
        first_parsed = record["first_decision"]["schema_validation"].get("parsed", {})
        second_parsed = record["second_decision"]["schema_validation"].get("parsed", {})
        rows.append(
            f"| {index} | {record['question']['question']} | "
            f"{first_parsed.get('action', 'invalid')} | "
            f"{second_parsed.get('action', 'invalid')} |"
        )
    markdown = """# P3 decide smoke outputs

This is a qualitative artifact. No question is marked pass or fail; Fable reviews
the complete thoughts, inputs, and mocked second-step behavior in the JSON file.

| # | Question | First action | Second action |
|---:|---|---|---|
""" + "\n".join(rows) + "\n\n" + (
        "Diagnostic only: tool-zero finish first attempts = "
        f"{finish_first}/{len(first_valid)}; identical repeats = {repeated}/{comparable}."
    )
    json_path, md_path = write_result_files("p3", result, markdown)
    print(f"Saved {json_path}\nSaved {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
