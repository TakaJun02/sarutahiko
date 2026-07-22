#!/usr/bin/env python3
"""P2 guided-JSON schema compliance and latency-overhead measurement."""

from __future__ import annotations

import os
from typing import Any

from poc_common import (
    client_from_env,
    decision_schema,
    format_number,
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

DECIDE_PROMPT = """You are the trial decide component for APU-Navi.
Select exactly one next action for the visitor question. Return JSON only with
thought, action, and action_input. Keep thought to one or two short Japanese
sentences. Available actions are retrieve, search, web_search,
campus_navigator, ask_user, and finish. A finish before any information tool is
invalid. Prefer an explicit assumption over ask_user when the answer would not
materially change.

Question: オープンキャンパスでは何ができますか？
No tools have been executed yet.
"""


def run_one(client, model: str, response_format: dict[str, Any] | None):
    try:
        response = client.chat(
            model=model,
            messages=[{"role": "user", "content": DECIDE_PROMPT}],
            max_tokens=int(os.environ.get("P2_MAX_TOKENS", "300")),
            temperature=float(os.environ.get("P2_TEMPERATURE", "0.2")),
            response_format=response_format,
        )
        validation = validate_decision(response["content"], set(ACTIONS))
        return {
            "ok": True,
            **response,
            "schema_validation": validation,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "schema_validation": {"valid": False, "error": str(exc)},
        }


def main() -> int:
    client = client_from_env()
    available_models = client.list_models()
    model = client.resolve_model(available_models)
    iterations = int(os.environ.get("P2_ITERATIONS", "20"))
    schema = decision_schema(ACTIONS)
    guided_format = response_format_for(schema)

    guided_records: list[dict[str, Any]] = []
    unguided_records: list[dict[str, Any]] = []
    order: list[str] = []
    for index in range(iterations):
        # Balance cache/warm-up bias: half the pairs run guided first.
        guided_first = index % 2 == 0
        modes = ["guided", "unguided"] if guided_first else ["unguided", "guided"]
        order.extend(modes)
        for mode in modes:
            record = run_one(
                client, model, guided_format if mode == "guided" else None
            )
            record["pair_index"] = index
            if mode == "guided":
                guided_records.append(record)
            else:
                unguided_records.append(record)

    guided_latencies = [
        record["latency_seconds"]
        for record in guided_records
        if record.get("ok") and isinstance(record.get("latency_seconds"), (int, float))
    ]
    unguided_latencies = [
        record["latency_seconds"]
        for record in unguided_records
        if record.get("ok") and isinstance(record.get("latency_seconds"), (int, float))
    ]
    guided_valid = sum(
        bool(record["schema_validation"].get("valid")) for record in guided_records
    )
    unguided_valid = sum(
        bool(record["schema_validation"].get("valid")) for record in unguided_records
    )
    guided_stats = numeric_summary(guided_latencies)
    unguided_stats = numeric_summary(unguided_latencies)
    guided_mean = guided_stats.get("mean")
    unguided_mean = unguided_stats.get("mean")
    overhead_seconds = (
        guided_mean - unguided_mean
        if isinstance(guided_mean, (int, float))
        and isinstance(unguided_mean, (int, float))
        else None
    )
    overhead_percent = (
        overhead_seconds / unguided_mean * 100.0
        if isinstance(overhead_seconds, (int, float)) and unguided_mean
        else None
    )

    result = {
        "gate": "P2",
        "metadata": metadata(client, model),
        "settings": {
            "iterations_per_mode": iterations,
            "temperature": float(os.environ.get("P2_TEMPERATURE", "0.2")),
            "max_tokens": int(os.environ.get("P2_MAX_TOKENS", "300")),
            "balanced_call_order": order,
        },
        "schema": schema,
        "prompt": DECIDE_PROMPT,
        "guided": {
            "valid_count": guided_valid,
            "total_count": iterations,
            "compliance_rate": guided_valid / iterations if iterations else None,
            "latency_seconds": guided_stats,
            "records": guided_records,
        },
        "unguided": {
            "valid_count": unguided_valid,
            "total_count": iterations,
            "compliance_rate": unguided_valid / iterations if iterations else None,
            "latency_seconds": unguided_stats,
            "records": unguided_records,
        },
        "latency_overhead": {
            "mean_seconds": overhead_seconds,
            "mean_percent_vs_unguided": overhead_percent,
        },
    }
    markdown = f"""# P2 guided JSON PoC summary

- Endpoint: `{client.config.base_url}`
- Model: `{model}`
- Guided schema compliance: {guided_valid}/{iterations} ({format_number((guided_valid / iterations * 100.0) if iterations else None)}%)
- Unguided schema compliance: {unguided_valid}/{iterations} ({format_number((unguided_valid / iterations * 100.0) if iterations else None)}%)
- Guided mean latency: {format_number(guided_mean)} s
- Unguided mean latency: {format_number(unguided_mean)} s
- Guided mean overhead: {format_number(overhead_seconds)} s ({format_number(overhead_percent)}%)

Calls are paired with identical messages; only `response_format` differs. This
artifact reports measurements only. Fable applies the P2 acceptance decision.
"""
    json_path, md_path = write_result_files("p2", result, markdown)
    print(f"Saved {json_path}\nSaved {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

