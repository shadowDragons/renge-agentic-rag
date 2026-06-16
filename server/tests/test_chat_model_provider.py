from langchain_core.messages import HumanMessage

from app.integrations.chat_model_provider import OpenAICompatibleChatBackend


class _FakeInvokeResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class _FakeStreamingResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode("utf-8") for line in lines]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def __iter__(self):
        return iter(self._lines)


def test_openai_compatible_chat_backend_stream_parses_sse_chunks(monkeypatch) -> None:
    backend = OpenAICompatibleChatBackend()

    def fake_urlopen(*args, **kwargs):
        return _FakeStreamingResponse(
            [
                'data: {"model":"mock-gpt","choices":[{"delta":{"content":"你好"},"finish_reason":null}]}',
                "",
                'data: {"model":"mock-gpt","choices":[{"delta":{"content":"，世界"},"finish_reason":null}]}',
                "data: [DONE]",
            ]
        )

    monkeypatch.setattr(
        "app.integrations.chat_model_provider.request.urlopen",
        fake_urlopen,
    )

    chunks = list(
        backend.stream(
            messages=[HumanMessage(content="你好")],
            model="mock-gpt",
            temperature=0.2,
        )
    )

    assert "".join(chunk.delta for chunk in chunks) == "你好，世界"
    assert all(chunk.model_name == "mock-gpt" for chunk in chunks)


def test_openai_compatible_chat_backend_invoke_extracts_usage(monkeypatch) -> None:
    backend = OpenAICompatibleChatBackend()

    def fake_urlopen(*args, **kwargs):
        return _FakeInvokeResponse(
            '{"model":"mock-gpt","choices":[{"message":{"content":"你好"}}],"usage":{"prompt_tokens":12,"completion_tokens":8,"total_tokens":20}}'
        )

    monkeypatch.setattr(
        "app.integrations.chat_model_provider.request.urlopen",
        fake_urlopen,
    )

    response = backend.invoke(
        messages=[HumanMessage(content="你好")],
        model="mock-gpt",
        temperature=0.2,
    )

    assert response.content == "你好"
    assert response.usage == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }


def test_openai_compatible_chat_backend_stream_extracts_usage(monkeypatch) -> None:
    backend = OpenAICompatibleChatBackend()

    def fake_urlopen(*args, **kwargs):
        return _FakeStreamingResponse(
            [
                'data: {"model":"mock-gpt","choices":[{"delta":{"content":"你好"},"finish_reason":null}]}',
                'data: {"model":"mock-gpt","choices":[{"delta":{"content":"，世界"},"finish_reason":"stop"}],"usage":{"prompt_tokens":12,"completion_tokens":8,"total_tokens":20}}',
                "data: [DONE]",
            ]
        )

    monkeypatch.setattr(
        "app.integrations.chat_model_provider.request.urlopen",
        fake_urlopen,
    )

    chunks = list(
        backend.stream(
            messages=[HumanMessage(content="你好")],
            model="mock-gpt",
            temperature=0.2,
        )
    )

    assert chunks[-1].usage == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }


def test_openai_compatible_chat_backend_honors_timeout_override(monkeypatch) -> None:
    backend = OpenAICompatibleChatBackend()
    captured_timeout: dict[str, int] = {}

    def fake_urlopen(*args, **kwargs):
        captured_timeout["value"] = kwargs["timeout"]
        return _FakeInvokeResponse(
            '{"model":"mock-gpt","choices":[{"message":{"content":"你好"}}]}'
        )

    monkeypatch.setattr(
        "app.integrations.chat_model_provider.request.urlopen",
        fake_urlopen,
    )

    response = backend.invoke(
        messages=[HumanMessage(content="你好")],
        model="mock-gpt",
        temperature=0.2,
        timeout_seconds=180,
    )

    assert response.content == "你好"
    assert captured_timeout["value"] == 180
