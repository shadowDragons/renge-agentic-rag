from types import SimpleNamespace

from app.integrations.langfuse_tracing import LangfuseObservation, LangfuseTracer


class _FakeSdkObservation:
    def __init__(self, observation_id: str = "obs-001") -> None:
        self.id = observation_id

    def update(self, **kwargs) -> None:
        return None

    def end(self) -> None:
        return None


def _build_tracer(client) -> LangfuseTracer:
    tracer = LangfuseTracer.__new__(LangfuseTracer)
    tracer.settings = SimpleNamespace(langfuse_capture_input_output=False)
    tracer.enabled = True
    tracer.client = client
    return tracer


def test_start_answer_generation_uses_explicit_trace_id() -> None:
    captured: dict = {}

    class FakeClient:
        def start_generation(self, **kwargs):
            captured.update(kwargs)
            return _FakeSdkObservation()

    tracer = _build_tracer(FakeClient())
    observation = tracer.start_answer_generation(
        model="deepseek-ai/DeepSeek-V4-Pro",
        trace_id="trace-123",
        input={"question": "员工请假需要做什么？"},
    )

    assert observation.trace_id
    assert captured["trace_context"] == {"trace_id": observation.trace_id}


def test_start_answer_generation_prefers_explicit_parent_observation() -> None:
    parent_calls: list[dict] = []
    client_calls: list[dict] = []

    class FakeClient:
        def start_generation(self, **kwargs):
            client_calls.append(kwargs)
            return _FakeSdkObservation("client-child")

    class FakeParentSdkObservation(_FakeSdkObservation):
        def start_generation(self, **kwargs):
            parent_calls.append(kwargs)
            return _FakeSdkObservation("parent-child")

    tracer = _build_tracer(FakeClient())
    parent = LangfuseObservation(
        client=tracer,
        name="workflow.compose_answer",
        sdk_observation=FakeParentSdkObservation("compose-parent"),
        trace_id="trace-123",
        observation_id="compose-parent",
    )

    observation = tracer.start_answer_generation(
        model="deepseek-ai/DeepSeek-V4-Pro",
        trace_id="trace-123",
        parent_observation=parent,
        input={"question": "员工请假需要做什么？"},
    )

    assert observation.observation_id == "parent-child"
    assert len(parent_calls) == 1
    assert client_calls == []
