from __future__ import annotations

from pathlib import Path

from knowledge.ingest.ingest import (
    build_embedding_text,
    build_knowledge_chunks,
    chunk_markdown,
    count_tokens,
    parse_frontmatter,
)


def test_parse_frontmatter_reads_required_metadata(tmp_path: Path) -> None:
    path = tmp_path / "sample.md"
    path.write_text(
        """---
id: sample-topic
category: facility
title: サンプル
source_urls:
  - https://example.test/source
retrieved_at: 2026-07-11
confidence: high
---

本文です。
""",
        encoding="utf-8",
    )

    document = parse_frontmatter(path)

    assert document.metadata["id"] == "sample-topic"
    assert document.metadata["source_urls"] == ["https://example.test/source"]
    assert document.body == "本文です。"


def test_chunk_markdown_splits_by_heading_and_limits_long_sections() -> None:
    long_body = " ".join(f"token{i}" for i in range(18))
    body = f"""導入文

## 見出しA
短い本文です。

## 見出しB
{long_body}
"""

    chunks = chunk_markdown(body, max_tokens=10, overlap_tokens=2)

    assert chunks[0] == "導入文"
    assert chunks[1].startswith("## 見出しA")
    assert len(chunks) > 3
    assert all(count_tokens(chunk) <= 10 for chunk in chunks[2:])


def test_build_knowledge_chunks_uses_stable_ids(tmp_path: Path) -> None:
    path = tmp_path / "sample.md"
    path.write_text(
        """---
id: sample-topic
category: access
title: アクセス
source_urls:
  - https://example.test/access
retrieved_at: 2026-07-11
confidence: medium
---

本文です。
""",
        encoding="utf-8",
    )
    document = parse_frontmatter(path)

    first = build_knowledge_chunks(document, ["chunk one", "chunk two"])
    second = build_knowledge_chunks(document, ["chunk one", "chunk two"])

    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]
    assert first[0].file_id == "sample-topic"
    assert first[1].chunk_index == 1
    assert first[0].source_urls == ["https://example.test/access"]


def test_build_embedding_text_includes_title_heading_and_chunk_text(tmp_path: Path) -> None:
    path = tmp_path / "sample.md"
    path.write_text(
        """---
id: sample-topic
category: lab
title: サイバーフィジカルシステム研究室（CPS研） メンバー一覧
source_urls:
  - https://example.test/members
retrieved_at: 2026-07-12
confidence: high
---

## 学生メンバー（Members）
以下は学生メンバーの一覧です。
""",
        encoding="utf-8",
    )
    document = parse_frontmatter(path)
    chunk = "## 学生メンバー（Members）\n以下は学生メンバーの一覧です。"

    assert build_embedding_text(document, chunk) == (
        "サイバーフィジカルシステム研究室（CPS研） メンバー一覧\n"
        "学生メンバー（Members）\n"
        "## 学生メンバー（Members）\n以下は学生メンバーの一覧です。"
    )
