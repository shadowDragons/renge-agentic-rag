from pydantic import BaseModel, Field


class EvaluationRunRequest(BaseModel):
    assistant_id: str = Field(min_length=1, max_length=36)
    dataset_key: str = Field(default="hr_small", max_length=64)
    dataset_path: str = Field(default="", max_length=1000)
    limit: int | None = Field(default=None, ge=1, le=100)
    top_k: int = Field(default=4, ge=1, le=10)
    write_scores_to_langfuse: bool = True


class EvaluationRunItemSummary(BaseModel):
    item_id: str
    question: str
    trace_id: str
    trace_url: str | None = None
    answer_preview: str
    fallback_reason: str | None = None
    retrieval_count: int = 0
    citation_count: int = 0
    citation_files: list[str] = Field(default_factory=list)
    prompt_name: str = ""
    prompt_version: int | None = None
    prompt_source: str = ""
    average_score: float = 0.0
    scores: dict[str, float] = Field(default_factory=dict)
    error: str = ""


class EvaluationRunResponse(BaseModel):
    run_id: str
    assistant_id: str
    assistant_name: str
    dataset_key: str
    dataset_path: str
    dataset_item_count: int
    success_count: int
    failure_count: int
    average_scores: dict[str, float] = Field(default_factory=dict)
    items: list[EvaluationRunItemSummary] = Field(default_factory=list)


class EvaluationDatasetSummary(BaseModel):
    key: str
    label: str
    description: str
    path: str
