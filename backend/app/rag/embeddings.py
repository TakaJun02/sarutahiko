from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any


class EmbeddingModel:
    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        *,
        device: str = "cpu",
        batch_size: int = 8,
        model: Any | None = None,
        backend: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        if model is not None:
            self._model = model
            self._backend = backend or "custom"
        else:
            self._model, self._backend = self._load_model()

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        normalized_texts = [text.replace("\n", " ").strip() for text in texts]
        if not normalized_texts:
            return []

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


def _to_float_list(vector: Any) -> list[float]:
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return [float(value) for value in vector]
