from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any

import httpx

QWEN3_QUERY_INSTRUCT_PREFIX = (
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\n"
    "Query: "
)
DEFAULT_REMOTE_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_LOCAL_EMBEDDING_MODEL = "BAAI/bge-m3"
QUERY_TIMEOUT_SECONDS = 8.0
DOCUMENT_TIMEOUT_SECONDS = 60.0


class EmbeddingModel:
    def __init__(
        self,
        model_name: str = DEFAULT_REMOTE_EMBEDDING_MODEL,
        *,
        device: str = "cpu",
        batch_size: int = 8,
        model: Any | None = None,
        backend: str | None = None,
        base_url: str | None = None,
        http_client_factory: Callable[[float], httpx.Client] | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else os.getenv("EMBEDDING_BASE_URL", "")).strip()
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.http_client_factory = http_client_factory or self._default_http_client
        if model is not None:
            self._model = model
            self._backend = backend or "custom"
        elif self.base_url:
            self._model = None
            self._backend = "remote"
        else:
            if self.model_name == DEFAULT_REMOTE_EMBEDDING_MODEL:
                self.model_name = DEFAULT_LOCAL_EMBEDDING_MODEL
            self._model, self._backend = self._load_model()

    def embed_query(self, text: str) -> list[float]:
        normalized_text = _normalize_embedding_text(text)
        if not normalized_text:
            normalized_text = text.strip()
        if self._backend == "remote":
            query_text = f"{QWEN3_QUERY_INSTRUCT_PREFIX}{normalized_text}"
            return self._embed_remote([query_text], timeout=QUERY_TIMEOUT_SECONDS)[0]
        return self.embed_documents([normalized_text])[0]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        normalized_texts = [_normalize_embedding_text(text) for text in texts]
        if not normalized_texts:
            return []

        if self._backend == "remote":
            return self._embed_remote(normalized_texts, timeout=DOCUMENT_TIMEOUT_SECONDS)

        if self._backend == "flag":
            encoded = self._model.encode(normalized_texts, batch_size=self.batch_size, max_length=8192)
            vectors = encoded["dense_vecs"] if isinstance(encoded, dict) else encoded
            return [_to_float_list(vector) for vector in vectors]

        if self._backend == "sentence-transformers":
            vectors = self._model.encode(
                normalized_texts,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return [_to_float_list(vector) for vector in vectors]

        if hasattr(self._model, "embed_documents"):
            return [list(map(float, vector)) for vector in self._model.embed_documents(normalized_texts)]
        if hasattr(self._model, "encode"):
            vectors = self._model.encode(normalized_texts)
            return [_to_float_list(vector) for vector in vectors]
        raise TypeError("custom embedding model must provide embed_documents() or encode()")

    def _load_model(self) -> tuple[Any, str]:
        try:
            from FlagEmbedding import BGEM3FlagModel

            try:
                return BGEM3FlagModel(self.model_name, use_fp16=False, devices=[self.device]), "flag"
            except TypeError:
                try:
                    return BGEM3FlagModel(self.model_name, use_fp16=False, device=self.device), "flag"
                except TypeError:
                    model = BGEM3FlagModel(self.model_name, use_fp16=False)
                    inner_model = getattr(model, "model", None)
                    if inner_model is not None and hasattr(inner_model, "to"):
                        inner_model.to(self.device)
                    return model, "flag"
        except ImportError:
            pass

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("FlagEmbedding or sentence-transformers is required for embeddings") from exc

        cache_folder = os.getenv("SENTENCE_TRANSFORMERS_HOME") or os.getenv("HF_HOME")
        return (
            SentenceTransformer(self.model_name, device=self.device, cache_folder=cache_folder),
            "sentence-transformers",
        )

    def _embed_remote(self, texts: Sequence[str], *, timeout: float) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self.base_url.rstrip('/')}/embeddings"
        payload = {"model": self.model_name, "input": list(texts)}
        with self.http_client_factory(timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        rows = data.get("data")
        if not isinstance(rows, list):
            raise ValueError("embedding response is missing data[]")
        if all(isinstance(row, dict) and isinstance(row.get("index"), int) for row in rows):
            rows = sorted(rows, key=lambda row: row["index"])

        vectors: list[list[float]] = []
        for row in rows:
            if not isinstance(row, dict) or "embedding" not in row:
                raise ValueError("embedding response row is missing embedding")
            vectors.append(_to_float_list(row["embedding"]))
        if len(vectors) != len(texts):
            raise ValueError("embedding response count does not match input count")
        return vectors

    @staticmethod
    def _default_http_client(timeout: float) -> httpx.Client:
        return httpx.Client(timeout=timeout)


def _to_float_list(vector: Any) -> list[float]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return [float(value) for value in vector]


def _normalize_embedding_text(text: str) -> str:
    return str(text).strip()
