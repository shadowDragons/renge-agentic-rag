from app.services import answer_generation as answer_generation_module
from app.schemas.chat import ChatCitation
from app.services.answer_generation import (
    AnswerGenerationService,
    build_no_retrieval_hits_answer,
    build_review_required_answer,
    managed_text_prompt_definitions,
)
from app.integrations.chat_model_provider import ChatModelResponse

_REAL_GENERATE_ANSWER = answer_generation_module.AnswerGenerationService.generate_answer


def test_answer_generation_uses_local_prompt_fallback_when_prompt_management_disabled(
    monkeypatch,
) -> None:
    captured_messages: dict = {}

    class FakeObservation:
        def end(self, **kwargs) -> None:
            return None

    class FakeTracer:
        def start_answer_generation(self, **kwargs):
            return FakeObservation()

    class FakeModelService:
        def invoke(self, **kwargs):
            captured_messages["messages"] = kwargs["messages"]
            return ChatModelResponse(
                content="员工报销需要提供发票和审批单。",
                model_name="mock-gpt",
                backend_name="mock-backend",
                usage=None,
            )

    monkeypatch.setattr(
        "app.services.answer_generation.get_langfuse_tracer",
        lambda: FakeTracer(),
    )
    monkeypatch.setattr(
        answer_generation_module.AnswerGenerationService,
        "generate_answer",
        _REAL_GENERATE_ANSWER,
    )

    service = AnswerGenerationService(model_service=FakeModelService())
    result = service.generate_answer(
        assistant_name="测试助理",
        system_prompt="请引用制度原文。",
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

    assert result.content == "员工报销需要提供发票和审批单。"
    assert result.prompt_name == "enterprise_rag_answer_generation"
    assert result.prompt_source == "local_fallback"
    assert result.prompt_version is None
    rendered_messages = captured_messages["messages"]
    assert any("员工报销需要什么材料" in str(message.content) for message in rendered_messages)
    assert any("请引用制度原文" in str(message.content) for message in rendered_messages)


def test_managed_text_prompt_helpers_render_local_fallbacks() -> None:
    no_hits = build_no_retrieval_hits_answer(
        assistant_name="知识库助理",
        question="怎么报销餐补？",
        selected_kb_ids=["kb-001"],
        selected_knowledge_base_id="kb-001",
    )
    review_required = build_review_required_answer(
        assistant_name="知识库助理",
        question="离职补偿怎么算？",
        review_reason="命中敏感规则",
    )

    assert "怎么报销餐补" in no_hits
    assert "kb-001" in no_hits
    assert "离职补偿怎么算" in review_required
    assert "命中敏感规则" in review_required


def test_managed_text_prompt_definitions_contains_seedable_prompts() -> None:
    definitions = managed_text_prompt_definitions()

    assert {item.name for item in definitions} >= {
        "enterprise_rag_no_retrieval_hits",
        "enterprise_rag_clarification_confirm_switch",
        "enterprise_rag_review_required",
        "enterprise_rag_review_rejected",
    }
