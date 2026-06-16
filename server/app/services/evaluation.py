from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import get_settings
from app.services.evaluation_datasets import EvaluationDatasetRegistry
from app.integrations.langfuse_tracing import get_langfuse_tracer, sanitize_citations
from app.workflows.chat_graph import build_chat_workflow


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _character_ngrams(text: str, *, size: int = 2) -> set[str]:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]", "", _normalize_text(text)).lower()
    if not normalized:
        return set()
    if len(normalized) <= size:
        return {normalized}
    return {normalized[index : index + size] for index in range(len(normalized) - size + 1)}


def _recall_score(expected_items: list[str], actual_text: str) -> float:
    normalized_items = [_normalize_text(item) for item in expected_items if _normalize_text(item)]
    if not normalized_items:
        return 0.0
    lowered_text = _normalize_text(actual_text).lower()
    matched = sum(1 for item in normalized_items if item.lower() in lowered_text)
    return round(matched / len(normalized_items), 4)


def _overlap_score(source_text: str, target_text: str) -> float:
    source_tokens = _character_ngrams(source_text)
    target_tokens = _character_ngrams(target_text)
    if not source_tokens or not target_tokens:
        return 0.0
    overlap = len(source_tokens & target_tokens)
    return round(overlap / len(source_tokens), 4)


def _clip_score(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


@dataclass(frozen=True)
class EvaluationDatasetItem:
    item_id: str
    question: str
    reference_answer: str
    expected_keywords: list[str] = field(default_factory=list)
    grounded_keywords: list[str] = field(default_factory=list)
    expected_citation_files: list[str] = field(default_factory=list)
    expected_min_citations: int = 1
    assistant_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationCandidate:
    question: str
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    trace_id: str = ""
    assistant_name: str = ""
    dataset_item_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationScore:
    name: str
    value: float
    comment: str = ""


@dataclass(frozen=True)
class EvaluationResult:
    candidate: EvaluationCandidate
    dataset_item: EvaluationDatasetItem | None
    scores: list[EvaluationScore]

    @property
    def summary(self) -> dict[str, float]:
        return {item.name: item.value for item in self.scores}

    @property
    def average_score(self) -> float:
        if not self.scores:
            return 0.0
        return round(sum(item.value for item in self.scores) / len(self.scores), 4)


@dataclass(frozen=True)
class EvaluationRunItemResult:
    item_id: str
    question: str
    trace_id: str
    answer_preview: str
    fallback_reason: str | None
    retrieval_count: int
    citation_count: int
    citation_files: list[str] = field(default_factory=list)
    prompt_name: str = ""
    prompt_version: int | None = None
    prompt_source: str = ""
    average_score: float = 0.0
    scores: dict[str, float] = field(default_factory=dict)
    error: str = ""
    trace_url: str | None = None


@dataclass(frozen=True)
class EvaluationRunResult:
    run_id: str
    assistant_id: str
    assistant_name: str
    dataset_path: str
    dataset_item_count: int
    success_count: int
    failure_count: int
    average_scores: dict[str, float]
    item_results: list[EvaluationRunItemResult]


class EvaluationService:
    """最小可用的离线评测服务。

    第一版先支持：
    - 加载本地 JSON dataset
    - 对 question/answer/citations 做启发式打分
    - 把三类 score 回写到 Langfuse
    """

    def load_dataset(self, dataset_path: str | Path) -> list[EvaluationDatasetItem]:
        path = Path(dataset_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("评测数据集必须是 JSON 数组。")
        return [self._parse_dataset_item(item) for item in payload]

    def __init__(self) -> None:
        self.settings = get_settings()
        self.dataset_registry = EvaluationDatasetRegistry()

    def load_default_hr_dataset(self) -> list[EvaluationDatasetItem]:
        return self.load_named_dataset("hr_small")

    def load_named_dataset(self, dataset_key: str) -> list[EvaluationDatasetItem]:
        definition = self.dataset_registry.require(dataset_key)
        return self.load_dataset(definition.path)

    def resolve_dataset_path(self, dataset_key: str) -> str:
        definition = self.dataset_registry.require(dataset_key)
        return str(definition.path)

    def evaluate_candidate(
        self,
        *,
        candidate: EvaluationCandidate,
        dataset_item: EvaluationDatasetItem | None = None,
    ) -> EvaluationResult:
        scores = [
            self._score_answer_relevance(candidate, dataset_item),
            self._score_groundedness(candidate, dataset_item),
            self._score_citation_quality(candidate, dataset_item),
        ]
        return EvaluationResult(
            candidate=candidate,
            dataset_item=dataset_item,
            scores=scores,
        )

    def evaluate_and_score_trace(
        self,
        *,
        trace_id: str,
        question: str,
        answer: str,
        citations: list[dict[str, Any]],
        dataset_item: EvaluationDatasetItem | None = None,
        assistant_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        result = self.evaluate_candidate(
            candidate=EvaluationCandidate(
                trace_id=trace_id,
                question=question,
                answer=answer,
                citations=citations,
                assistant_name=assistant_name,
                dataset_item_id=dataset_item.item_id if dataset_item else "",
                metadata=metadata or {},
            ),
            dataset_item=dataset_item,
        )
        self.score_trace(trace_id=trace_id, result=result)
        return result

    def score_trace(self, *, trace_id: str, result: EvaluationResult) -> None:
        if not trace_id.strip():
            return
        tracer = get_langfuse_tracer()
        for item in result.scores:
            tracer.score(
                trace_id=trace_id,
                name=item.name,
                value=item.value,
                comment=item.comment,
            )

    def run_dataset_for_assistant(
        self,
        *,
        assistant,
        dataset_items: list[EvaluationDatasetItem],
        dataset_path: str,
        limit: int | None = None,
        top_k: int = 4,
        write_scores_to_langfuse: bool = True,
    ) -> EvaluationRunResult:
        selected_items = dataset_items[:limit] if limit else list(dataset_items)
        workflow = build_chat_workflow(include_compose_answer=True)
        tracer = get_langfuse_tracer()
        run_id = uuid4().hex
        item_results: list[EvaluationRunItemResult] = []
        score_buckets: dict[str, list[float]] = {
            "answer_relevance": [],
            "groundedness": [],
            "citation_quality": [],
        }

        for item in selected_items:
            trace_id = uuid4().hex
            trace_url = tracer.get_trace_url(trace_id=trace_id)
            trace_metadata = {
                "assistant_id": assistant.assistant_id,
                "assistant_name": assistant.assistant_name,
                "dataset_run_id": run_id,
                "dataset_item_id": item.item_id,
                "dataset_path": dataset_path,
                "evaluation_mode": "offline_dataset",
                "top_k": top_k,
                "selected_kb_ids": list(assistant.default_kb_ids or []),
            }
            try:
                workflow_input = self._build_workflow_input(
                    assistant=assistant,
                    question=item.question,
                    top_k=top_k,
                )
                trace_input = self._build_trace_input(
                    assistant=assistant,
                    item=item,
                    top_k=top_k,
                )
                with tracer.trace_chat_turn(
                    trace_id=trace_id,
                    name="enterprise-rag.evaluation_turn",
                    user_id=f"evaluation:{assistant.assistant_id}",
                    session_id=run_id,
                    input=trace_input,
                    metadata=trace_metadata,
                ):
                    workflow_result = workflow.invoke(
                        workflow_input,
                        config={"configurable": {"thread_id": trace_id}},
                    )

                answer = _normalize_text(str(workflow_result.get("answer", "")))
                fallback_reason = workflow_result.get("fallback_reason")
                citations = [
                    citation.model_dump(mode="json")
                    if hasattr(citation, "model_dump")
                    else dict(citation)
                    for citation in workflow_result.get("citations", [])
                ]
                result = self.evaluate_candidate(
                    candidate=EvaluationCandidate(
                        trace_id=trace_id,
                        question=item.question,
                        answer=answer,
                        citations=citations,
                        assistant_name=assistant.assistant_name,
                        dataset_item_id=item.item_id,
                        metadata={"dataset_run_id": run_id},
                    ),
                    dataset_item=item,
                )
                if write_scores_to_langfuse:
                    self.score_trace(trace_id=trace_id, result=result)

                for name, value in result.summary.items():
                    if name in score_buckets:
                        score_buckets[name].append(value)

                tracer.finalize_chat_turn(
                    trace_id=trace_id,
                    name="enterprise-rag.evaluation_turn",
                    user_id=f"evaluation:{assistant.assistant_id}",
                    session_id=run_id,
                    input=trace_input,
                    output=self._build_trace_output(
                        answer=answer,
                        citations=citations,
                        fallback_reason=fallback_reason,
                        retrieval_count=int(
                            workflow_result.get("retrieval_count", len(citations))
                        ),
                        scores=result.summary,
                    ),
                    metadata={
                        **trace_metadata,
                        "dataset_reference_answer": item.reference_answer,
                        "fallback_reason": fallback_reason,
                        "retrieval_count": int(
                            workflow_result.get("retrieval_count", len(citations))
                        ),
                        "prompt_name": str(workflow_result.get("prompt_name", "")),
                        "prompt_version": workflow_result.get("prompt_version"),
                        "prompt_source": str(workflow_result.get("prompt_source", "")),
                        "citations": sanitize_citations(citations),
                        "evaluation_scores": result.summary,
                        "evaluation_average_score": result.average_score,
                    },
                )
                item_results.append(
                    EvaluationRunItemResult(
                        item_id=item.item_id,
                        question=item.question,
                        trace_id=trace_id,
                        trace_url=trace_url,
                        answer_preview=_normalize_text(answer)[:200],
                        fallback_reason=fallback_reason,
                        retrieval_count=int(
                            workflow_result.get("retrieval_count", len(citations))
                        ),
                        citation_count=len(citations),
                        citation_files=[
                            _normalize_text(str(citation.get("file_name", "")))
                            for citation in citations
                            if _normalize_text(str(citation.get("file_name", "")))
                        ],
                        prompt_name=_normalize_text(
                            str(workflow_result.get("prompt_name", ""))
                        ),
                        prompt_version=(
                            int(workflow_result["prompt_version"])
                            if workflow_result.get("prompt_version") is not None
                            else None
                        ),
                        prompt_source=_normalize_text(
                            str(workflow_result.get("prompt_source", ""))
                        ),
                        average_score=result.average_score,
                        scores=result.summary,
                    )
                )
            except Exception as exc:
                item_results.append(
                    EvaluationRunItemResult(
                        item_id=item.item_id,
                        question=item.question,
                        trace_id=trace_id,
                        trace_url=trace_url,
                        answer_preview="",
                        fallback_reason="evaluation_failed",
                        retrieval_count=0,
                        citation_count=0,
                        error=str(exc).strip(),
                    )
                )

        success_count = sum(1 for item in item_results if not item.error)
        failure_count = len(item_results) - success_count
        average_scores = {
            key: round(sum(values) / len(values), 4) if values else 0.0
            for key, values in score_buckets.items()
        }
        tracer.flush()
        return EvaluationRunResult(
            run_id=run_id,
            assistant_id=assistant.assistant_id,
            assistant_name=assistant.assistant_name,
            dataset_path=dataset_path,
            dataset_item_count=len(selected_items),
            success_count=success_count,
            failure_count=failure_count,
            average_scores=average_scores,
            item_results=item_results,
        )

    def _score_answer_relevance(
        self,
        candidate: EvaluationCandidate,
        dataset_item: EvaluationDatasetItem | None,
    ) -> EvaluationScore:
        answer = _normalize_text(candidate.answer)
        if not answer:
            return EvaluationScore(
                name="answer_relevance",
                value=0.0,
                comment="回答为空，未回应用户问题。",
            )

        expected_keywords = dataset_item.expected_keywords if dataset_item else []
        reference_answer = dataset_item.reference_answer if dataset_item else ""
        keyword_score = _recall_score(expected_keywords, answer)
        overlap_score = max(
            _overlap_score(candidate.question, answer),
            _overlap_score(reference_answer, answer),
        )
        if expected_keywords:
            value = _clip_score(keyword_score * 0.7 + overlap_score * 0.3)
            missing = [
                keyword
                for keyword in expected_keywords
                if keyword.lower() not in answer.lower()
            ]
            comment = (
                "回答覆盖了主要问题要点。"
                if not missing
                else f"回答缺少部分关键点：{', '.join(missing[:4])}"
            )
        else:
            value = _clip_score(overlap_score)
            comment = "按问题与回答的文本重合度做启发式评分。"
        return EvaluationScore(
            name="answer_relevance",
            value=value,
            comment=comment,
        )

    def _score_groundedness(
        self,
        candidate: EvaluationCandidate,
        dataset_item: EvaluationDatasetItem | None,
    ) -> EvaluationScore:
        citations = [self._normalize_citation(item) for item in candidate.citations]
        if not citations:
            return EvaluationScore(
                name="groundedness",
                value=0.0,
                comment="没有引用片段，回答缺少可验证依据。",
            )

        citation_text = "\n".join(item.get("content", "") for item in citations)
        grounded_keywords = dataset_item.grounded_keywords if dataset_item else []
        answer = _normalize_text(candidate.answer)
        keyword_in_citations = _recall_score(grounded_keywords, citation_text)
        keyword_in_answer = _recall_score(grounded_keywords, answer)
        overlap_score = _overlap_score(answer, citation_text)
        if grounded_keywords:
            value = _clip_score(
                keyword_in_citations * 0.5
                + keyword_in_answer * 0.2
                + overlap_score * 0.3
            )
            missing = [
                keyword
                for keyword in grounded_keywords
                if keyword.lower() not in citation_text.lower()
            ]
            comment = (
                "回答关键结论都能在引用片段中找到依据。"
                if not missing
                else f"引用片段缺少部分依据：{', '.join(missing[:4])}"
            )
        else:
            value = _clip_score(overlap_score)
            comment = "按回答与引用片段的文本重合度做启发式评分。"
        return EvaluationScore(
            name="groundedness",
            value=value,
            comment=comment,
        )

    def _score_citation_quality(
        self,
        candidate: EvaluationCandidate,
        dataset_item: EvaluationDatasetItem | None,
    ) -> EvaluationScore:
        citations = [self._normalize_citation(item) for item in candidate.citations]
        if not citations:
            return EvaluationScore(
                name="citation_quality",
                value=0.0,
                comment="没有检索到引用片段，无法支撑回答。",
            )

        citation_files = [str(item.get("file_name", "")).strip() for item in citations]
        citation_text = "\n".join(item.get("content", "") for item in citations)
        expected_files = dataset_item.expected_citation_files if dataset_item else []
        expected_min_citations = (
            max(1, int(dataset_item.expected_min_citations))
            if dataset_item
            else 1
        )
        expected_keywords = (
            dataset_item.expected_keywords
            if dataset_item and dataset_item.expected_keywords
            else dataset_item.grounded_keywords if dataset_item else []
        )

        count_score = _clip_score(len(citations) / expected_min_citations)
        file_score = (
            _recall_score(expected_files, "\n".join(citation_files))
            if expected_files
            else 1.0
        )
        coverage_score = (
            _recall_score(expected_keywords, citation_text)
            if expected_keywords
            else _overlap_score(candidate.question, citation_text)
        )
        value = _clip_score(count_score * 0.3 + file_score * 0.4 + coverage_score * 0.3)

        missing_files = [
            file_name
            for file_name in expected_files
            if file_name.lower() not in "\n".join(citation_files).lower()
        ]
        if missing_files:
            comment = f"缺少预期引用文件：{', '.join(missing_files[:3])}"
        elif len(citations) < expected_min_citations:
            comment = f"引用数量偏少，当前 {len(citations)}，预期至少 {expected_min_citations}。"
        else:
            comment = "检索片段数量和来源基本可支撑当前问题。"
        return EvaluationScore(
            name="citation_quality",
            value=value,
            comment=comment,
        )

    def _parse_dataset_item(self, payload: Any) -> EvaluationDatasetItem:
        if not isinstance(payload, dict):
            raise ValueError("评测数据集条目必须是对象。")
        item_id = _normalize_text(str(payload.get("item_id", "")))
        question = _normalize_text(str(payload.get("question", "")))
        reference_answer = _normalize_text(str(payload.get("reference_answer", "")))
        if not item_id or not question or not reference_answer:
            raise ValueError("评测数据集条目必须包含 item_id、question、reference_answer。")
        return EvaluationDatasetItem(
            item_id=item_id,
            question=question,
            reference_answer=reference_answer,
            expected_keywords=self._normalize_list(payload.get("expected_keywords")),
            grounded_keywords=self._normalize_list(payload.get("grounded_keywords")),
            expected_citation_files=self._normalize_list(
                payload.get("expected_citation_files")
            ),
            expected_min_citations=max(
                1,
                int(payload.get("expected_min_citations", 1) or 1),
            ),
            assistant_name=_normalize_text(str(payload.get("assistant_name", ""))),
            metadata=dict(payload.get("metadata") or {}),
        )

    def _normalize_list(self, payload: Any) -> list[str]:
        if payload is None:
            return []
        if isinstance(payload, str):
            payload = [item.strip() for item in payload.split(",")]
        if not isinstance(payload, list):
            raise ValueError("评测数据集字段必须是字符串数组。")
        return [_normalize_text(str(item)) for item in payload if _normalize_text(str(item))]

    def _normalize_citation(self, payload: Any) -> dict[str, Any]:
        if hasattr(payload, "model_dump"):
            payload = payload.model_dump(mode="json")
        return {
            "file_name": _normalize_text(str((payload or {}).get("file_name", ""))),
            "content": _normalize_text(str((payload or {}).get("content", ""))),
            "knowledge_base_id": _normalize_text(
                str((payload or {}).get("knowledge_base_id", ""))
            ),
        }

    def _build_workflow_input(
        self,
        *,
        assistant,
        question: str,
        top_k: int,
    ) -> dict[str, Any]:
        return {
            "assistant_id": assistant.assistant_id,
            "assistant_name": assistant.assistant_name,
            "assistant_config": {
                "assistant_id": assistant.assistant_id,
                "assistant_name": assistant.assistant_name,
                "system_prompt": assistant.system_prompt,
                "default_model": assistant.default_model,
                "default_kb_ids": list(assistant.default_kb_ids or []),
                "review_rules": [],
                "review_enabled": False,
            },
            "session_status": "active",
            "session_runtime_context": {},
            "session_runtime_state": "idle",
            "question": question,
            "requested_knowledge_base_ids": [],
            "message_history": [],
            "top_k": top_k,
            "llm_timeout_seconds_override": self.settings.evaluation_llm_timeout_seconds,
            "review_interrupt_enabled": False,
        }

    def _build_trace_input(
        self,
        *,
        assistant,
        item: EvaluationDatasetItem,
        top_k: int,
    ) -> dict[str, Any]:
        return {
            "assistant_id": assistant.assistant_id,
            "assistant_name": assistant.assistant_name,
            "dataset_item_id": item.item_id,
            "question": item.question,
            "reference_answer": item.reference_answer,
            "expected_keywords": list(item.expected_keywords),
            "grounded_keywords": list(item.grounded_keywords),
            "expected_citation_files": list(item.expected_citation_files),
            "top_k": top_k,
        }

    def _build_trace_output(
        self,
        *,
        answer: str,
        citations: list[dict[str, Any]],
        fallback_reason: str | None,
        retrieval_count: int,
        scores: dict[str, float],
    ) -> dict[str, Any]:
        return {
            "answer": answer,
            "fallback_reason": fallback_reason,
            "retrieval_count": retrieval_count,
            "citation_files": [
                _normalize_text(str(citation.get("file_name", "")))
                for citation in citations
                if _normalize_text(str(citation.get("file_name", "")))
            ],
            "scores": dict(scores),
        }
