from __future__ import annotations

import json

import httpx

from app.rag.embeddings import (
    DEFAULT_LOCAL_EMBEDDING_MODEL,
    EmbeddingModel,
    QWEN3_QUERY_INSTRUCT_PREFIX,
)


def _remote_embedding_factory(requests: list[dict], timeouts: list[float]):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append({"url": str(request.url), "payload": payload})
        rows = [
            {"index": index, "embedding": [float(index), float(index) + 0.5]}
            for index, _ in enumerate(payload["input"])
        ]
        return httpx.Response(200, json={"data": list(reversed(rows))}, request=request)

    def factory(timeout: float) -> httpx.Client:
        timeouts.append(timeout)
        return httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout)

    return factory


def test_remote_embed_query_adds_qwen3_instruction_prefix_and_uses_query_timeout() -> None:
    requests: list[dict] = []
    timeouts: list[float] = []
    model = EmbeddingModel(
        model_name="Qwen/Qwen3-Embedding-8B",
        base_url="http://embedding.test/v1",
        http_client_factory=_remote_embedding_factory(requests, timeouts),
    )

    vector = model.embed_query("サイバーフィジカルシステム研究室 出展")

    assert vector == [0.0, 0.5]
    assert timeouts == [8.0]
    assert requests[0]["url"] == "http://embedding.test/v1/embeddings"
    assert requests[0]["payload"]["model"] == "Qwen/Qwen3-Embedding-8B"
    assert requests[0]["payload"]["input"] == [
        f"{QWEN3_QUERY_INSTRUCT_PREFIX}サイバーフィジカルシステム研究室 出展"
    ]


def test_remote_embed_documents_sends_batch_without_instruction_and_uses_ingest_timeout() -> None:
    requests: list[dict] = []
    timeouts: list[float] = []
    model = EmbeddingModel(
        model_name="Qwen/Qwen3-Embedding-8B",
        base_url="http://embedding.test/v1/",
        http_client_factory=_remote_embedding_factory(requests, timeouts),
    )
    texts = [
        "サイバーフィジカルシステム研究室（CPS研）\n出展\n本文",
        "別タイトル\n見出し\n本文",
    ]

    vectors = model.embed_documents(texts)

    assert vectors == [[0.0, 0.5], [1.0, 1.5]]
    assert timeouts == [60.0]
    assert requests[0]["url"] == "http://embedding.test/v1/embeddings"
    assert requests[0]["payload"]["input"] == texts


def test_embedding_model_falls_back_to_local_bge_m3_when_remote_base_url_is_unset(monkeypatch) -> None:
    class LocalModel:
        def embed_documents(self, texts):
            return [[len(text)] for text in texts]

    def fake_load_model(self):
        return LocalModel(), "custom"

    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    monkeypatch.setattr(EmbeddingModel, "_load_model", fake_load_model)

    model = EmbeddingModel(model_name="Qwen/Qwen3-Embedding-8B")

    assert model.model_name == DEFAULT_LOCAL_EMBEDDING_MODEL
    assert model.embed_documents(["local text"]) == [[10.0]]
