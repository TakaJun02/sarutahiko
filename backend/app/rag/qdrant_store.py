from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from app.rag.embeddings import EmbeddingModel
from app.rag.models import KnowledgeChunk


class CampusKnowledgeStore:
    def __init__(
        self,
        *,
        url: str,
        collection_name: str = "campus_knowledge",
        embedding_model: EmbeddingModel,
        client: Any | None = None,
    ) -> None:
        self.url = url
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self._client = client or self._create_client()

    async def search(self, query: str, *, limit: int = 6) -> list[KnowledgeChunk]:
        query_vector = self.embedding_model.embed_query(query)
        points = await asyncio.to_thread(self._search_sync, query_vector, limit)
        return [self._point_to_chunk(point) for point in points]

    async def upsert_chunks(self, chunks: Sequence[KnowledgeChunk], vectors: Sequence[Sequence[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        points = [self._to_point(chunk, vector) for chunk, vector in zip(chunks, vectors, strict=True)]
        await asyncio.to_thread(self._client.upsert, collection_name=self.collection_name, points=points)

    async def recreate_collection(self, vector_size: int) -> None:
        await asyncio.to_thread(self._recreate_collection_sync, vector_size)

    async def ensure_collection(self, vector_size: int) -> None:
        exists = await asyncio.to_thread(self._collection_exists)
        if not exists:
            await self.recreate_collection(vector_size)

    async def health(self) -> dict:
        await asyncio.to_thread(self._client.get_collections)
        return {"ok": True, "status": "reachable", "url": self.url, "collection": self.collection_name}

    def _search_sync(self, query_vector: list[float], limit: int) -> list[Any]:
        if hasattr(self._client, "search"):
            return self._client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
                with_payload=True,
            )
        response = self._client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=limit,
            with_payload=True,
        )
        return list(getattr(response, "points", response))

    def _recreate_collection_sync(self, vector_size: int) -> None:
        from qdrant_client.models import Distance, VectorParams

        vectors_config = VectorParams(size=vector_size, distance=Distance.COSINE)
        if hasattr(self._client, "recreate_collection"):
            self._client.recreate_collection(collection_name=self.collection_name, vectors_config=vectors_config)
            return
        if self._collection_exists():
            self._client.delete_collection(collection_name=self.collection_name)
        self._client.create_collection(collection_name=self.collection_name, vectors_config=vectors_config)

    def _collection_exists(self) -> bool:
        try:
            self._client.get_collection(collection_name=self.collection_name)
            return True
        except Exception:
            return False

    @staticmethod
    def _point_to_chunk(point: Any) -> KnowledgeChunk:
        payload = getattr(point, "payload", None) or {}
        return KnowledgeChunk(
            id=str(getattr(point, "id", payload.get("id", ""))),
            text=str(payload.get("chunk", payload.get("text", ""))),
            category=str(payload.get("category", "")),
            confidence=str(payload.get("confidence", "")),
            title=str(payload.get("title", "")),
            source_urls=list(payload.get("source_urls", [])),
            score=getattr(point, "score", None),
            file_id=payload.get("file_id"),
            chunk_index=payload.get("chunk_index"),
        )

    @staticmethod
    def _to_point(chunk: KnowledgeChunk, vector: Sequence[float]) -> Any:
        from qdrant_client.models import PointStruct

        payload = {
            "category": chunk.category,
            "confidence": chunk.confidence,
            "title": chunk.title,
            "source_urls": chunk.source_urls,
            "chunk": chunk.text,
            "file_id": chunk.file_id,
            "chunk_index": chunk.chunk_index,
        }
        return PointStruct(id=chunk.id, vector=list(vector), payload=payload)

    def _create_client(self) -> Any:
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise RuntimeError("qdrant-client is required for Qdrant access") from exc
        return QdrantClient(url=self.url)
