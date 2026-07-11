from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import load_settings  # noqa: E402
from app.rag.embeddings import EmbeddingModel  # noqa: E402
from app.rag.models import KnowledgeChunk  # noqa: E402
from app.rag.qdrant_store import CampusKnowledgeStore  # noqa: E402

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", re.UNICODE)
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+.+$", re.MULTILINE)
STABLE_ID_NAMESPACE = uuid.UUID("b9499827-2758-4b72-bc99-cbfb92c37f69")


@dataclass(frozen=True)
class ParsedDocument:
    path: Path
    metadata: dict[str, Any]
    body: str


def parse_frontmatter(path: Path) -> ParsedDocument:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path} is missing YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError(f"{path} has unterminated YAML frontmatter")
    metadata = yaml.safe_load(text[4:end]) or {}
    body = text[end + len("\n---\n") :].strip()
    _validate_metadata(path, metadata)
    return ParsedDocument(path=path, metadata=metadata, body=body)


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


def build_knowledge_chunks(document: ParsedDocument, chunks: list[str]) -> list[KnowledgeChunk]:
    document_id = str(document.metadata["id"])
    return [
        KnowledgeChunk(
            id=str(uuid.uuid5(STABLE_ID_NAMESPACE, f"{document_id}:{index}")),
            text=chunk,
            category=str(document.metadata["category"]),
            confidence=str(document.metadata["confidence"]),
            title=str(document.metadata["title"]),
            source_urls=list(document.metadata["source_urls"]),
            file_id=document_id,
            chunk_index=index,
        )
        for index, chunk in enumerate(chunks)
    ]


def load_documents(knowledge_dir: Path) -> list[ParsedDocument]:
    documents: list[ParsedDocument] = []
    for path in sorted(knowledge_dir.glob("*.md")):
        if path.name == "SOURCES.md":
            continue
        documents.append(parse_frontmatter(path))
    return documents


async def ingest(*, recreate: bool = False, knowledge_dir: Path | None = None) -> int:
    settings = load_settings()
    root = knowledge_dir or REPO_ROOT / "knowledge"
    documents = load_documents(root)
    chunks: list[KnowledgeChunk] = []
    for document in documents:
        chunks.extend(build_knowledge_chunks(document, chunk_markdown(document.body)))

    if not chunks:
        return 0

    embedding_model = EmbeddingModel(model_name=settings.embedding_model, device="cpu")
    vectors = embedding_model.embed_documents([chunk.text for chunk in chunks])
    store = CampusKnowledgeStore(
        url=settings.qdrant_url,
        collection_name=settings.qdrant_collection,
        embedding_model=embedding_model,
    )
    if recreate:
        await store.recreate_collection(vector_size=len(vectors[0]))
    else:
        await store.ensure_collection(vector_size=len(vectors[0]))
    await store.upsert_chunks(chunks, vectors)
    return len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Markdown knowledge into Qdrant.")
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate the Qdrant collection before upsert.")
    parser.add_argument(
        "--knowledge-dir",
        type=Path,
        default=REPO_ROOT / "knowledge",
        help="Directory containing knowledge Markdown files.",
    )
    args = parser.parse_args()
    count = asyncio.run(ingest(recreate=args.recreate, knowledge_dir=args.knowledge_dir))
    print(f"Upserted {count} chunks into Qdrant.")


def _validate_metadata(path: Path, metadata: dict[str, Any]) -> None:
    required = {"id", "category", "title", "source_urls", "retrieved_at", "confidence"}
    missing = sorted(required.difference(metadata))
    if missing:
        raise ValueError(f"{path} frontmatter is missing: {', '.join(missing)}")
    if not isinstance(metadata["source_urls"], list) or not metadata["source_urls"]:
        raise ValueError(f"{path} source_urls must be a non-empty list")


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


if __name__ == "__main__":
    main()
