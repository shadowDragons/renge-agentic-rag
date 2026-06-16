import json

from app.core.config import Settings
from app.integrations.embedding_provider import OpenAICompatibleEmbeddingBackend


def test_embedding_payload_omits_dimensions_for_bge_model(monkeypatch) -> None:
    backend = OpenAICompatibleEmbeddingBackend()
    backend.settings = Settings(
        OPENAI_EMBEDDING_MODEL_NAME="BAAI/bge-large-zh-v1.5",
    )

    payload = backend._build_payload(["hello"])

    assert payload == {
        "input": ["hello"],
        "model": "BAAI/bge-large-zh-v1.5",
    }


def test_embedding_payload_includes_dimensions_for_text_embedding_3_model(
    monkeypatch,
) -> None:
    backend = OpenAICompatibleEmbeddingBackend()
    backend.settings = Settings(
        OPENAI_EMBEDDING_MODEL_NAME="text-embedding-3-large",
        OPENAI_EMBEDDING_DIMENSIONS=1024,
    )

    payload = backend._build_payload(["hello"])

    assert payload == {
        "input": ["hello"],
        "model": "text-embedding-3-large",
        "dimensions": 1024,
    }


def test_openai_compatible_embedding_backend_parses_response(monkeypatch) -> None:
    backend = OpenAICompatibleEmbeddingBackend()
    backend.settings = Settings(
        OPENAI_EMBEDDING_MODEL_NAME="BAAI/bge-large-zh-v1.5",
        OPENAI_EMBEDDING_DIMENSIONS=3,
        SILICONFLOW_API_KEY="sk-test",
    )

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "data": [
                        {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(http_request, timeout, context):
        body = json.loads(http_request.data.decode("utf-8"))
        assert "dimensions" not in body
        return _FakeResponse()

    monkeypatch.setattr(
        "app.integrations.embedding_provider.request.urlopen",
        fake_urlopen,
    )

    vectors = backend.embed_texts(["hello"])

    assert vectors == [[0.1, 0.2, 0.3]]
