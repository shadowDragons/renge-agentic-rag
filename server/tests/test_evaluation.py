from pathlib import Path

from app.services import evaluation as evaluation_module
from app.services.evaluation import (
    EvaluationCandidate,
    EvaluationDatasetItem,
    EvaluationService,
)
from app.services.evaluation_datasets import EvaluationDatasetRegistry


def test_evaluation_service_loads_default_hr_dataset() -> None:
    service = EvaluationService()

    items = service.load_default_hr_dataset()

    assert len(items) >= 6
    assert items[0].item_id == "hr_leave_001"
    assert items[0].expected_citation_files == ["02_请假制度.txt"]


def test_evaluation_dataset_registry_lists_three_named_datasets() -> None:
    registry = EvaluationDatasetRegistry()

    definitions = registry.list_definitions()

    assert {item.key for item in definitions} == {
        "hr_small",
        "support_small",
        "prd_small",
    }


def test_evaluation_service_loads_named_support_dataset() -> None:
    service = EvaluationService()

    items = service.load_named_dataset("support_small")

    assert len(items) >= 6
    assert items[0].item_id == "support_ticket_001"
    assert items[0].expected_citation_files == ["02_工单升级SOP.txt"]


def test_evaluation_service_scores_candidate_against_dataset_item() -> None:
    service = EvaluationService()
    dataset_item = EvaluationDatasetItem(
        item_id="hr_leave_001",
        question="员工请年假至少要提前多久申请？",
        reference_answer="员工申请年假至少需要提前 2 个工作日发起申请。",
        expected_keywords=["年假", "提前", "2 个工作日", "申请"],
        grounded_keywords=["年假", "提前 2 个工作日", "申请"],
        expected_citation_files=["02_请假制度.txt"],
        expected_min_citations=1,
    )

    result = service.evaluate_candidate(
        candidate=EvaluationCandidate(
            question=dataset_item.question,
            answer="员工申请年假至少要提前 2 个工作日提交申请。",
            citations=[
                {
                    "file_name": "02_请假制度.txt",
                    "content": "年假：需至少提前 2 个工作日发起申请，且原则上需在自然年度内使用完毕。",
                }
            ],
        ),
        dataset_item=dataset_item,
    )

    summary = result.summary
    assert summary["answer_relevance"] >= 0.8
    assert summary["groundedness"] >= 0.7
    assert summary["citation_quality"] >= 0.8


def test_evaluation_service_writes_scores_to_langfuse() -> None:
    service = EvaluationService()
    captured_scores: list[dict] = []

    class FakeTracer:
        def score(self, **kwargs) -> None:
            captured_scores.append(kwargs)

    original_get_tracer = evaluation_module.get_langfuse_tracer
    evaluation_module.get_langfuse_tracer = lambda: FakeTracer()
    try:
        result = service.evaluate_candidate(
            candidate=EvaluationCandidate(
                question="忘记打卡后要怎么补卡？",
                answer="员工需要提交补卡申请并说明原因。",
                citations=[
                    {
                        "file_name": "11_考勤补卡说明.md",
                        "content": "员工忘记打卡后，需要按说明提交补卡申请，并说明原因。",
                    }
                ],
                trace_id="trace-001",
            ),
            dataset_item=EvaluationDatasetItem(
                item_id="hr_attendance_001",
                question="忘记打卡后要怎么补卡？",
                reference_answer="员工忘记打卡后需要按考勤补卡说明提交补卡申请，并说明原因。",
                expected_keywords=["补卡", "提交申请", "说明原因"],
                grounded_keywords=["补卡", "提交补卡申请", "说明原因"],
                expected_citation_files=["11_考勤补卡说明.md"],
                expected_min_citations=1,
            ),
        )
        service.score_trace(trace_id="trace-001", result=result)
    finally:
        evaluation_module.get_langfuse_tracer = original_get_tracer

    assert len(captured_scores) == 3
    assert {item["name"] for item in captured_scores} == {
        "answer_relevance",
        "groundedness",
        "citation_quality",
    }
    assert all(item["trace_id"] == "trace-001" for item in captured_scores)


def test_evaluation_dataset_file_exists() -> None:
    dataset_path = (
        Path(__file__).resolve().parents[2]
        / "kb-file"
        / "evaluation_datasets"
        / "hr_small_dataset.json"
    )

    assert dataset_path.exists()


def test_evaluation_workflow_input_uses_evaluation_timeout_override() -> None:
    service = EvaluationService()

    class FakeAssistant:
        assistant_id = "asst-001"
        assistant_name = "测试助理"
        system_prompt = "请用中文回答。"
        default_model = "deepseek-ai/DeepSeek-V4-Pro"
        default_kb_ids = ["kb-001"]

    workflow_input = service._build_workflow_input(
        assistant=FakeAssistant(),
        question="员工请年假至少要提前多久申请？",
        top_k=4,
    )

    assert workflow_input["llm_timeout_seconds_override"] == (
        service.settings.evaluation_llm_timeout_seconds
    )
