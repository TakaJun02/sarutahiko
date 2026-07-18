from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.rag.qdrant_store import CampusKnowledgeStore


pytestmark = pytest.mark.asyncio


class FakeQdrantClient:
    def __init__(self, points):
        self.points = points
        self.scroll_calls = []

    def scroll(
        self,
        *,
        collection_name,
        scroll_filter,
        limit,
        offset,
        with_payload,
        with_vectors,
    ):
        self.scroll_calls.append(
            {
                "collection_name": collection_name,
                "scroll_filter": scroll_filter,
                "limit": limit,
                "offset": offset,
                "with_payload": with_payload,
                "with_vectors": with_vectors,
            }
        )
        return self.points, None


async def test_get_file_chunks_scrolls_by_file_id_and_sorts_chunk_index(monkeypatch) -> None:
    to_thread_calls = []

    async def fake_to_thread(func, *args):
        to_thread_calls.append((func, args))
        return func(*args)

    monkeypatch.setattr("app.rag.qdrant_store.asyncio.to_thread", fake_to_thread)
    client = FakeQdrantClient(
        [
            SimpleNamespace(
                id="b-1",
                score=None,
                payload={
                    "file_id": "doc-b",
                    "chunk_index": 1,
                    "chunk": "B1",
                    "category": "lab",
                    "confidence": "high",
                    "title": "B",
                    "source_urls": ["https://example.test/b"],
                },
            ),
            SimpleNamespace(
                id="a-0",
                score=None,
                payload={
                    "file_id": "doc-a",
                    "chunk_index": 0,
                    "chunk": "A0",
                    "category": "lab",
                    "confidence": "high",
                    "title": "A",
                    "source_urls": ["https://example.test/a"],
                },
            ),
            SimpleNamespace(
                id="b-0",
                score=None,
                payload={
                    "file_id": "doc-b",
                    "chunk_index": 0,
                    "chunk": "B0",
                    "category": "lab",
                    "confidence": "high",
                    "title": "B",
                    "source_urls": ["https://example.test/b"],
                },
            ),
        ]
    )
    store = CampusKnowledgeStore(
        url="http://qdrant.test",
        collection_name="test_collection",
        embedding_model=object(),
        client=client,
    )

    chunks = await store.get_file_chunks(["doc-b", "doc-a"])

    assert to_thread_calls == [(store._get_file_chunks_sync, (["doc-b", "doc-a"],))]
    assert [(chunk.file_id, chunk.chunk_index, chunk.text) for chunk in chunks] == [
        ("doc-b", 0, "B0"),
        ("doc-b", 1, "B1"),
        ("doc-a", 0, "A0"),
    ]
    assert client.scroll_calls[0]["collection_name"] == "test_collection"
    assert client.scroll_calls[0]["with_vectors"] is False
