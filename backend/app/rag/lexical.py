from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import yaml

from app.rag.models import KnowledgeChunk

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", re.UNICODE)
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+.+$", re.MULTILINE)
KATAKANA_RUN_PATTERN = re.compile(r"[ァ-ヶー]+")
KANJI_RUN_PATTERN = re.compile(r"[一-龯々〆ヵヶ]+")
STABLE_ID_NAMESPACE = uuid.UUID("b9499827-2758-4b72-bc99-cbfb92c37f69")
VARIANT_SUFFIXES = ("研究グループ", "について", "研究室", "先生", "教授", "講座", "学科")
MAX_LEXICAL_HITS = 6


@dataclass(frozen=True)
class LexicalSection:
    chunk: KnowledgeChunk
    heading: str
    normalized_text: str
    normalized_title_heading: str


@dataclass(frozen=True)
class SectionHit:
    chunk: KnowledgeChunk
    distinct_keyword_hits: int
    title_heading_keyword_hit: bool
    total_hits: int
    body_length: int


@dataclass(frozen=True)
class LexicalSearchOutcome:
    hits: list[SectionHit]
    searched_keywords: list[str]
    variant_keywords: list[str]
    variants_attempted: bool


class CampusLexicalSearch:
    def __init__(self, knowledge_dir: Path | str) -> None:
        self.knowledge_dir = Path(knowledge_dir)
        self._sections: list[LexicalSection] | None = None

    def grep_sections(self, keywords: Sequence[str]) -> list[SectionHit]:
        return self.grep_sections_with_trace(keywords).hits

    def grep_sections_with_trace(self, keywords: Sequence[str]) -> LexicalSearchOutcome:
        primary_keywords = normalize_keywords(keywords)
        primary_hits = self._search_once(primary_keywords)
        if primary_hits:
            return LexicalSearchOutcome(
                hits=primary_hits,
                searched_keywords=primary_keywords,
                variant_keywords=[],
                variants_attempted=False,
            )

        variant_keywords = generate_keyword_variants(primary_keywords)
        variant_hits = self._search_once(variant_keywords)
        return LexicalSearchOutcome(
            hits=variant_hits,
            searched_keywords=variant_keywords if variant_keywords else primary_keywords,
            variant_keywords=variant_keywords,
            variants_attempted=bool(variant_keywords),
        )

    def _search_once(self, keywords: Sequence[str]) -> list[SectionHit]:
        normalized_keywords = normalize_keywords(keywords)
        if not normalized_keywords:
            return []

        hits: list[SectionHit] = []
        for section in self._load_sections():
            matched_keywords: list[str] = []
            total_hits = 0
            title_heading_hit = False
            for keyword in normalized_keywords:
                normalized_keyword = normalize_text(keyword)
                count = section.normalized_text.count(normalized_keyword)
                if count <= 0:
                    continue
                matched_keywords.append(keyword)
                total_hits += count
                title_heading_hit = title_heading_hit or normalized_keyword in section.normalized_title_heading
            if not matched_keywords:
                continue

            distinct_hits = len(matched_keywords)
            chunk = KnowledgeChunk(
                id=section.chunk.id,
                text=section.chunk.text,
                category=section.chunk.category,
                confidence=section.chunk.confidence,
                title=section.chunk.title,
                source_urls=section.chunk.source_urls,
                score=_lexical_score(distinct_hits, title_heading_hit, total_hits, len(section.chunk.text)),
                file_id=section.chunk.file_id,
                chunk_index=section.chunk.chunk_index,
                grep_hit=True,
                grep_keywords=tuple(matched_keywords),
            )
            hits.append(
                SectionHit(
                    chunk=chunk,
                    distinct_keyword_hits=distinct_hits,
                    title_heading_keyword_hit=title_heading_hit,
                    total_hits=total_hits,
                    body_length=len(section.chunk.text),
                )
            )

        return sorted(
            hits,
            key=lambda hit: (
                -hit.distinct_keyword_hits,
                -int(hit.title_heading_keyword_hit),
                -hit.total_hits,
                -hit.body_length,
            ),
        )[:MAX_LEXICAL_HITS]

    def _load_sections(self) -> list[LexicalSection]:
        if self._sections is not None:
            return self._sections

        sections: list[LexicalSection] = []
        if not self.knowledge_dir.exists():
            self._sections = []
            return self._sections

        for path in sorted(self.knowledge_dir.glob("*.md")):
            if path.name == "SOURCES.md":
                continue
            document = _parse_frontmatter(path)
            document_id = str(document["metadata"]["id"])
            chunks = chunk_markdown(document["body"])
            for index, text in enumerate(chunks):
                title = str(document["metadata"]["title"])
                heading = _extract_heading(text)
                chunk = KnowledgeChunk(
                    id=str(uuid.uuid5(STABLE_ID_NAMESPACE, f"{document_id}:{index}")),
                    text=text,
                    category=str(document["metadata"]["category"]),
                    confidence=str(document["metadata"]["confidence"]),
                    title=title,
                    source_urls=list(document["metadata"]["source_urls"]),
                    file_id=document_id,
                    chunk_index=index,
                )
                searchable = "\n".join((title, heading, text))
                sections.append(
                    LexicalSection(
                        chunk=chunk,
                        heading=heading,
                        normalized_text=normalize_text(searchable),
                        normalized_title_heading=normalize_text("\n".join((title, heading))),
                    )
                )

        self._sections = sections
        return self._sections


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def normalize_keywords(keywords: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_keyword in keywords:
        keyword = " ".join(str(raw_keyword).strip().split())
        if not keyword:
            continue
        key = normalize_text(keyword)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(keyword)
    return normalized


def generate_keyword_variants(keywords: Sequence[str]) -> list[str]:
    variants: list[str] = []
    seen: set[str] = set()
    suffix_keys = {normalize_text(suffix) for suffix in VARIANT_SUFFIXES}

    def add(value: str) -> None:
        value = " ".join(value.strip().split())
        if not value:
            return
        key = normalize_text(value)
        if key in suffix_keys:
            return
        if key in seen:
            return
        seen.add(key)
        variants.append(value)

    for keyword in normalize_keywords(keywords):
        stripped = strip_keyword_suffix(keyword)
        if stripped != keyword:
            add(stripped)
        katakana_run = _longest_run(KATAKANA_RUN_PATTERN, stripped)
        kanji_run = _longest_run(KANJI_RUN_PATTERN, stripped)
        if katakana_run and len(katakana_run) >= 2:
            add(katakana_run)
        if kanji_run and len(kanji_run) >= 2:
            add(kanji_run)

    return variants


def strip_keyword_suffix(keyword: str) -> str:
    stripped = keyword.strip()
    changed = True
    while changed:
        changed = False
        for suffix in VARIANT_SUFFIXES:
            if stripped.endswith(suffix) and len(stripped) > len(suffix):
                stripped = stripped[: -len(suffix)].strip()
                changed = True
                break
    return stripped


def chunk_markdown(body: str, *, max_tokens: int = 500, overlap_tokens: int = 50) -> list[str]:
    sections = _split_by_heading(body)
    chunks: list[str] = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if count_tokens(section) <= max_tokens:
            chunks.append(section)
            continue
        chunks.extend(_split_long_text(section, max_tokens=max_tokens, overlap_tokens=overlap_tokens))
    return chunks


def count_tokens(text: str) -> int:
    return len(TOKEN_PATTERN.findall(text))


def _parse_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path} is missing YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError(f"{path} has unterminated YAML frontmatter")
    metadata = yaml.safe_load(text[4:end]) or {}
    body = text[end + len("\n---\n") :].strip()
    _validate_metadata(path, metadata)
    return {"metadata": metadata, "body": body}


def _validate_metadata(path: Path, metadata: dict[str, Any]) -> None:
    required = {"id", "category", "title", "source_urls", "confidence"}
    missing = sorted(required.difference(metadata))
    if missing:
        raise ValueError(f"{path} frontmatter is missing: {', '.join(missing)}")
    if not isinstance(metadata["source_urls"], list):
        raise ValueError(f"{path} source_urls must be a list")


def _split_by_heading(body: str) -> list[str]:
    matches = list(HEADING_PATTERN.finditer(body))
    if not matches:
        return [body]

    sections: list[str] = []
    if matches[0].start() > 0:
        sections.append(body[: matches[0].start()])
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append(body[match.start() : end])
    return sections


def _split_long_text(text: str, *, max_tokens: int, overlap_tokens: int) -> list[str]:
    spans = [match.span() for match in TOKEN_PATTERN.finditer(text)]
    if not spans:
        return [text]
    chunks: list[str] = []
    start_token = 0
    while start_token < len(spans):
        end_token = min(start_token + max_tokens, len(spans))
        start_char = spans[start_token][0]
        end_char = spans[end_token - 1][1]
        chunks.append(text[start_char:end_char].strip())
        if end_token == len(spans):
            break
        start_token = max(end_token - overlap_tokens, start_token + 1)
    return chunks


def _extract_heading(text: str) -> str:
    match = HEADING_PATTERN.search(text)
    if not match:
        return ""
    return match.group(0).lstrip("#").strip()


def _longest_run(pattern: re.Pattern[str], text: str) -> str:
    runs = pattern.findall(text)
    if not runs:
        return ""
    return max(runs, key=len)


def _lexical_score(
    distinct_keyword_hits: int,
    title_heading_keyword_hit: bool,
    total_hits: int,
    body_length: int,
) -> float:
    return (
        distinct_keyword_hits * 1000
        + int(title_heading_keyword_hit) * 100
        + total_hits
        + min(body_length, 10000) / 100000
    )
