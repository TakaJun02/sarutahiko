from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeChunk:
    id: str
    text: str
    category: str
    confidence: str
    title: str
    source_urls: list[str]
    score: float | None = None
    file_id: str | None = None
    chunk_index: int | None = None
