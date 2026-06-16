from fastapi.testclient import TestClient


def test_system_can_run_hr_dataset_evaluation(
    client: TestClient,
    monkeypatch,
) -> None:
    def fake_retrieve(self, knowledge_base_id: str, query: str, top_k: int) -> list[dict]:
        if "病假" in query:
            return [
                {
                    "chunk_id": "chunk-sick-leave",
                    "document_id": "doc-sick-leave",
                    "knowledge_base_id": knowledge_base_id,
                    "chunk_index": 0,
                    "file_name": "02_请假制度.txt",
                    "content": "若连续病假超过 3 天，则必须提供二级及以上医院证明。",
                    "score": 0.96,
                    "vector_score": 0.88,
                    "lexical_score": 0.99,
                    "embedding_backend": "local_hash",
                }
            ]
        return [
            {
                "chunk_id": "chunk-annual-leave",
                "document_id": "doc-annual-leave",
                "knowledge_base_id": knowledge_base_id,
                "chunk_index": 0,
                "file_name": "02_请假制度.txt",
                "content": "年假：需至少提前 2 个工作日发起申请，且原则上需在自然年度内使用完毕。",
                "score": 0.95,
                "vector_score": 0.86,
                "lexical_score": 0.98,
                "embedding_backend": "local_hash",
            }
        ]

    monkeypatch.setattr(
        "app.services.retrieval.RetrievalService.retrieve",
        fake_retrieve,
    )

    response = client.post(
        "/api/v1/system/evaluations/run",
        json={
            "assistant_id": "asst-demo-001",
            "dataset_key": "hr_small",
            "limit": 2,
            "top_k": 4,
            "write_scores_to_langfuse": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assistant_id"] == "asst-demo-001"
    assert payload["dataset_key"] == "hr_small"
    assert payload["dataset_item_count"] == 2
    assert payload["success_count"] == 2
    assert payload["failure_count"] == 0
    assert set(payload["average_scores"]) == {
        "answer_relevance",
        "groundedness",
        "citation_quality",
    }
    assert len(payload["items"]) == 2
    assert payload["items"][0]["trace_id"]
    assert "trace_url" in payload["items"][0]
    assert payload["items"][0]["citation_count"] >= 1
    assert "02_请假制度.txt" in payload["items"][0]["citation_files"]
    assert payload["items"][0]["prompt_name"] == "enterprise_rag_answer_generation"
    assert payload["items"][0]["prompt_source"] in {
        "local_fallback",
        "langfuse",
        "langfuse_fallback",
    }


def test_system_evaluation_rejects_unknown_dataset_key(client: TestClient) -> None:
    response = client.post(
        "/api/v1/system/evaluations/run",
        json={
            "assistant_id": "asst-demo-001",
            "dataset_key": "unknown_dataset",
        },
    )

    assert response.status_code == 400
    assert "dataset_key" in response.json()["detail"]


def test_system_lists_named_evaluation_datasets(client: TestClient) -> None:
    response = client.get("/api/v1/system/evaluations/datasets")

    assert response.status_code == 200
    payload = response.json()
    assert {item["key"] for item in payload} == {
        "hr_small",
        "support_small",
        "prd_small",
    }
