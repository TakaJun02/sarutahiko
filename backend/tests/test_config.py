from __future__ import annotations

from app.core.config import DEFAULT_LLM_CONTEXT_WINDOW, load_settings


def test_effective_context_window_defaults_to_16384(monkeypatch) -> None:
    monkeypatch.delenv("VLLM_MAX_MODEL_LEN", raising=False)
    monkeypatch.delenv("LLM_CONTEXT_WINDOW", raising=False)

    assert load_settings().llm_context_window == DEFAULT_LLM_CONTEXT_WINDOW == 16384


def test_vllm_max_model_len_takes_precedence_over_legacy_window(monkeypatch) -> None:
    monkeypatch.setenv("VLLM_MAX_MODEL_LEN", "12288")
    monkeypatch.setenv("LLM_CONTEXT_WINDOW", "8192")

    assert load_settings().llm_context_window == 12288


def test_legacy_context_window_remains_a_fallback(monkeypatch) -> None:
    monkeypatch.delenv("VLLM_MAX_MODEL_LEN", raising=False)
    monkeypatch.setenv("LLM_CONTEXT_WINDOW", "8192")

    assert load_settings().llm_context_window == 8192
