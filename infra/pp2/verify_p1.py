#!/usr/bin/env python3
"""P1/P4 measurements: reachability, context, throughput, and prefix cache."""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from poc_common import (
    calibrate_prompt,
    client_from_env,
    format_number,
    metadata,
    numeric_summary,
    write_result_files,
)


def error_record(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": str(exc)}


def run_stream_batch(
    *,
    client,
    model: str,
    prompt: str,
    concurrency: int,
    output_tokens: int,
) -> dict[str, Any]:
    def one_request(index: int) -> dict[str, Any]:
        unique_prompt = (
            f"Unique request marker {index}-{time.time_ns()}.\n" + prompt
        )
        return client.stream_chat(
            model=model,
            messages=[{"role": "user", "content": unique_prompt}],
            max_tokens=output_tokens,
            temperature=0.2,
        )

    started = time.monotonic()
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(one_request, index) for index in range(concurrency)]
        for future in as_completed(futures):
            try:
                records.append(future.result())
            except Exception as exc:  # Keep all parallel outcomes in the artifact.
                errors.append(str(exc))
    batch_elapsed = time.monotonic() - started
    total_completion_tokens = sum(
        record["completion_tokens"]
        for record in records
        if isinstance(record.get("completion_tokens"), int)
    )
    return {
        "concurrency": concurrency,
        "ok": not errors and len(records) == concurrency,
        "batch_elapsed_seconds": batch_elapsed,
        "aggregate_output_tokens_per_second_including_prefill": (
            total_completion_tokens / batch_elapsed if batch_elapsed else None
        ),
        "ttft_seconds": numeric_summary(
            [record["ttft_seconds"] for record in records]
        ),
        "per_request_decode_tokens_per_second": numeric_summary(
            [
                record["decode_tokens_per_second"]
                for record in records
                if isinstance(record.get("decode_tokens_per_second"), (int, float))
            ]
        ),
        "requests": records,
        "errors": errors,
    }


def main() -> int:
    client = client_from_env()
    context_target = int(os.environ.get("P1_CONTEXT_TOKENS", "15000"))
    perf_prompt_target = int(os.environ.get("P1_PERF_PROMPT_TOKENS", "2000"))
    perf_output_tokens = int(os.environ.get("P1_PERF_OUTPUT_TOKENS", "256"))
    prefix_target = int(os.environ.get("P1_PREFIX_TOKENS", "8000"))

    result: dict[str, Any] = {
        "gate": "P1/P4",
        "settings": {
            "context_target_tokens": context_target,
            "performance_prompt_target_tokens": perf_prompt_target,
            "performance_output_tokens": perf_output_tokens,
            "prefix_target_tokens": prefix_target,
        },
    }

    try:
        available_models = client.list_models()
        model = client.resolve_model(available_models)
    except Exception as exc:
        result["connectivity"] = error_record(exc)
        markdown = f"# P1/P4 PoC summary\n\n/v1/models failed: `{exc}`"
        json_path, md_path = write_result_files("p1", result, markdown)
        print(f"Saved {json_path}\nSaved {md_path}")
        return 1

    result["metadata"] = metadata(client, model)
    result["connectivity"] = {
        "ok": True,
        "available_models": available_models,
        "selected_model": model,
    }

    try:
        context_prompt, calibrated_tokens = calibrate_prompt(
            client, model, context_target, label="context-window"
        )
        completion = client.chat(
            model=model,
            messages=[{"role": "user", "content": context_prompt}],
            max_tokens=16,
            temperature=0.0,
        )
        usage = completion.get("usage", {})
        measured_prompt_tokens = usage.get("prompt_tokens")
        result["context_window"] = {
            "ok": True,
            "target_tokens": context_target,
            "tokenize_count_before_chat_template": calibrated_tokens,
            "measured_prompt_tokens": measured_prompt_tokens,
            "latency_seconds": completion["latency_seconds"],
            "finish_reason": completion["finish_reason"],
        }
    except Exception as exc:
        result["context_window"] = error_record(exc)

    try:
        perf_prompt, perf_prompt_tokens = calibrate_prompt(
            client, model, perf_prompt_target, label="throughput"
        )
        result["throughput"] = {
            "tokenize_count_before_chat_template": perf_prompt_tokens,
            "concurrency_1": run_stream_batch(
                client=client,
                model=model,
                prompt=perf_prompt,
                concurrency=1,
                output_tokens=perf_output_tokens,
            ),
            "concurrency_4": run_stream_batch(
                client=client,
                model=model,
                prompt=perf_prompt,
                concurrency=4,
                output_tokens=perf_output_tokens,
            ),
        }
    except Exception as exc:
        result["throughput"] = error_record(exc)

    try:
        shared_prefix, prefix_tokens = calibrate_prompt(
            client, model, prefix_target, label="prefix-cache"
        )
        first = client.stream_chat(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": shared_prefix + "\nSuffix A: answer A briefly.",
                }
            ],
            max_tokens=32,
            temperature=0.0,
        )
        second = client.stream_chat(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": shared_prefix + "\nSuffix B: answer B briefly.",
                }
            ],
            max_tokens=32,
            temperature=0.0,
        )
        reduction = (
            (first["ttft_seconds"] - second["ttft_seconds"])
            / first["ttft_seconds"]
            * 100.0
            if first["ttft_seconds"]
            else None
        )
        result["prefix_caching"] = {
            "ok": True,
            "shared_prefix_tokens_before_chat_template": prefix_tokens,
            "first_ttft_seconds": first["ttft_seconds"],
            "second_ttft_seconds": second["ttft_seconds"],
            "ttft_reduction_percent": reduction,
            "first_request": first,
            "second_request": second,
        }
    except Exception as exc:
        result["prefix_caching"] = error_record(exc)

    throughput = result.get("throughput", {})
    c1 = throughput.get("concurrency_1", {}) if isinstance(throughput, dict) else {}
    c4 = throughput.get("concurrency_4", {}) if isinstance(throughput, dict) else {}
    prefix = result.get("prefix_caching", {})
    context = result.get("context_window", {})
    markdown = f"""# P1/P4 PoC summary

- Endpoint: `{client.config.base_url}`
- Model: `{model}`
- /v1/models: OK
- Context request: {'OK' if context.get('ok') else 'FAILED'} (measured prompt tokens: {context.get('measured_prompt_tokens', 'n/a')})
- 1-concurrency mean TTFT: {format_number(c1.get('ttft_seconds', {}).get('mean'))} s
- 1-concurrency mean decode: {format_number(c1.get('per_request_decode_tokens_per_second', {}).get('mean'))} tok/s
- 4-concurrency mean TTFT: {format_number(c4.get('ttft_seconds', {}).get('mean'))} s
- 4-concurrency aggregate output: {format_number(c4.get('aggregate_output_tokens_per_second_including_prefill'))} tok/s
- Prefix-cache first TTFT: {format_number(prefix.get('first_ttft_seconds'))} s
- Prefix-cache second TTFT: {format_number(prefix.get('second_ttft_seconds'))} s
- Prefix-cache TTFT reduction: {format_number(prefix.get('ttft_reduction_percent'))}%

This artifact reports measurements only. Fable applies the P1/P4 acceptance decision.
"""
    json_path, md_path = write_result_files("p1", result, markdown)
    print(f"Saved {json_path}\nSaved {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
