from __future__ import annotations

import pytest

from app.agent.thought_stream import THOUGHT_TEXT_LIMIT, ThoughtStreamExtractor


def _extract(chunks: list[str]) -> ThoughtStreamExtractor:
    extractor = ThoughtStreamExtractor()
    for chunk in chunks:
        extractor.feed(chunk)
    return extractor


def test_extracts_thought_across_every_chunk_boundary() -> None:
    raw = (
        '{\n  "thought" \t : "資料を\\n確認し、\\"GI512\\" と '
        'C:\\\\map\\/floor を調べます。", '
        '"action":"search","action_input":{"keywords":["GI512"]}}'
    )
    expected = '資料を 確認し、"GI512" と C:\\map/floor を調べます。'

    for split_at in range(len(raw) + 1):
        extractor = _extract([raw[:split_at], raw[split_at:]])
        assert extractor.text == expected
        assert extractor.finished is True


def test_decodes_unicode_escapes_and_surrogate_pairs_across_single_char_chunks() -> None:
    raw = '{"thought":"\\u79cb\\u7530\\uD83D\\uDE80","action":"finish"}'

    extractor = _extract(list(raw))

    assert extractor.text == "秋田🚀"


def test_ignores_nested_thought_before_top_level_thought() -> None:
    raw = (
        '{"metadata":{"thought":"表示しない"},'
        '"thought":"トップレベルだけ表示します。","action":"finish"}'
    )

    extractor = _extract(list(raw))

    assert extractor.text == "トップレベルだけ表示します。"


def test_collapses_literal_and_escaped_whitespace() -> None:
    raw = '{"thought":"  資料を\\n\\t  丁寧に   確認します。  ","action":"finish"}'

    extractor = _extract([raw])

    assert extractor.text == "資料を 丁寧に 確認します。"


@pytest.mark.parametrize(
    "marker",
    ["{", "}", "```", "action_input", "システムプロンプト"],
)
def test_marker_guard_stops_partial_results(marker: str) -> None:
    raw = f'{{"thought":"安全な前半 {marker} 秘密","action":"finish"}}'
    extractor = ThoughtStreamExtractor()
    emitted = [value for char in raw if (value := extractor.feed(char)) is not None]

    assert extractor.guarded is True
    assert all(marker not in value for value in emitted)
    assert extractor.feed("ignored") is None


def test_caps_cumulative_display_at_120_characters() -> None:
    extractor = _extract([f'{{"thought":"{"あ" * 140}","action":"finish"}}'])

    assert THOUGHT_TEXT_LIMIT == 120
    assert extractor.text == "あ" * THOUGHT_TEXT_LIMIT
    assert len(extractor.text) == THOUGHT_TEXT_LIMIT
