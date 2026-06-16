from app.services import answer_generation as answer_generation_module
from app.schemas.chat import ChatCitation
from app.services.answer_generation import AnswerGenerationService
from app.integrations.chat_model_provider import ChatModelResponse

_REAL_GENERATE_ANSWER = answer_generation_module.AnswerGenerationService.generate_answer


def test_answer_generation_reports_usage_to_langfuse(monkeypatch) -> None:
    captured_end: dict = {}

    class FakeObservation:
        def end(self, **kwargs) -> None:
            captured_end.update(kwargs)

    class FakeTracer:
        def start_answer_generation(self, **kwargs):
            return FakeObservation()

    class FakeModelService:
        def invoke(self, **kwargs):
            return ChatModelResponse(
                content="员工报销需要提供发票和审批单。",
                model_name="deepseek-ai/DeepSeek-V4-Pro",
                backend_name="mock-backend",
                usage={
                    "prompt_tokens": 100,
                    "completion_tokens": 25,
                    "total_tokens": 125,
                },
            )

    monkeypatch.setattr(
        answer_generation_module,
        "get_langfuse_tracer",
        lambda: FakeTracer(),
    )
    monkeypatch.setattr(
        answer_generation_module.AnswerGenerationService,
        "generate_answer",
        _REAL_GENERATE_ANSWER,
    )

    service = AnswerGenerationService(model_service=FakeModelService())
    service.generate_answer(
        assistant_name="测试助理",
        system_prompt="请用中文回答。",
        question="员工报销需要什么材料？",
        citations=[
            ChatCitation(
                chunk_id="chunk-001",
                document_id="doc-001",
                knowledge_base_id="kb-001",
                chunk_index=0,
                file_name="报销制度.md",
                content="员工报销需要提供发票和审批单。",
                score=0.93,
                vector_score=0.86,
                lexical_score=0.97,
                embedding_backend="local_hash",
            )
        ],
        selected_kb_ids=["kb-001"],
        selected_knowledge_base_id="kb-001",
        model_name="mock-gpt",
    )

    assert captured_end["usage_details"] == {
        "input": 100,
        "output": 25,
        "total": 125,
    }
    assert captured_end["cost_details"] == {
        "input": 0.0003,
        "output": 0.00015,
        "total": 0.00045,
    }


def test_answer_generation_passes_timeout_override_to_model_service(monkeypatch) -> None:
    captured_invoke: dict = {}

    class FakeObservation:
        def end(self, **kwargs) -> None:
            return None

    class FakeTracer:
        def start_answer_generation(self, **kwargs):
            return FakeObservation()

    class FakeModelService:
        def invoke(self, **kwargs):
            captured_invoke.update(kwargs)
            return ChatModelResponse(
                content="员工报销需要提供发票和审批单。",
                model_name="deepseek-ai/DeepSeek-V4-Pro",
                backend_name="mock-backend",
                usage=None,
            )

    monkeypatch.setattr(
        answer_generation_module,
        "get_langfuse_tracer",
        lambda: FakeTracer(),
    )
    monkeypatch.setattr(
        answer_generation_module.AnswerGenerationService,
        "generate_answer",
        _REAL_GENERATE_ANSWER,
    )

    service = AnswerGenerationService(model_service=FakeModelService())
    service.generate_answer(
        assistant_name="测试助理",
        system_prompt="请用中文回答。",
        question="员工报销需要什么材料？",
        citations=[
            ChatCitation(
                chunk_id="chunk-001",
                document_id="doc-001",
                knowledge_base_id="kb-001",
                chunk_index=0,
                file_name="报销制度.md",
                content="员工报销需要提供发票和审批单。",
                score=0.93,
                vector_score=0.86,
                lexical_score=0.97,
                embedding_backend="local_hash",
            )
        ],
        selected_kb_ids=["kb-001"],
        selected_knowledge_base_id="kb-001",
        model_name="mock-gpt",
        timeout_seconds=180,
    )

    assert captured_invoke["timeout_seconds"] == 180
