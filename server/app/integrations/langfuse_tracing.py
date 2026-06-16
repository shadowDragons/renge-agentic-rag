"""Optional Langfuse instrumentation for the RAG runtime.

Langfuse is intentionally kept behind this small adapter so observability remains
best-effort and never changes chat behavior when disabled or misconfigured.
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any
from uuid import UUID

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_current_trace_id: ContextVar[str] = ContextVar("langfuse_trace_id", default="")
_current_root_observation: ContextVar[Any] = ContextVar(
    "langfuse_root_observation",
    default=None,
)
_current_observation_stack: ContextVar[tuple[Any, ...]] = ContextVar(
    "langfuse_observation_stack",
    default=(),
)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _truncate(text: str, limit: int) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def _normalize_trace_id(trace_id: str) -> str:
    candidate = str(trace_id or "").strip().lower()
    if not candidate:
        return ""
    try:
        return UUID(candidate).hex
    except ValueError:
        pass
    if len(candidate) == 32 and all(ch in "0123456789abcdef" for ch in candidate):
        return candidate
    return hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:32]


def _safe_payload(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _safe_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_payload(item) for item in value]
    if hasattr(value, "model_dump"):
        return _safe_payload(value.model_dump(mode="json"))
    return str(value)


def sanitize_citations(citations: list[Any]) -> list[dict[str, Any]]:
    settings = get_settings()
    items: list[dict[str, Any]] = []
    for citation in citations:
        payload = (
            citation.model_dump(mode="json")
            if hasattr(citation, "model_dump")
            else dict(citation)
        )
        content = str(payload.get("content", ""))
        item = {
            "chunk_id": payload.get("chunk_id", ""),
            "document_id": payload.get("document_id", ""),
            "knowledge_base_id": payload.get("knowledge_base_id", ""),
            "chunk_index": payload.get("chunk_index", 0),
            "file_name": payload.get("file_name", ""),
            "score": payload.get("score", 0.0),
            "vector_score": payload.get("vector_score", 0.0),
            "lexical_score": payload.get("lexical_score", 0.0),
            "embedding_backend": payload.get("embedding_backend", ""),
            "content_hash": _hash_text(content) if content else "",
        }
        if settings.langfuse_capture_input_output:
            item["content_preview"] = _truncate(
                content,
                settings.langfuse_citation_content_limit,
            )
        items.append(item)
    return items


def workflow_span_name(node_name: str) -> str:
    alias = {
        "retrieve_context": "retrieval",
    }.get(node_name, node_name)
    return f"workflow.{alias}"


@dataclass
class LangfuseObservation:
    client: "LangfuseTracer"
    name: str
    kind: str = "span"
    input: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    started_at: float = field(default_factory=time.perf_counter)
    level: str = "DEFAULT"
    status_message: str = ""
    sdk_observation: Any = None
    stack_token: Any = None
    trace_id: str = ""
    observation_id: str = ""

    def end(
        self,
        *,
        output: Any = None,
        metadata: dict[str, Any] | None = None,
        level: str | None = None,
        status_message: str = "",
        usage_details: dict[str, int] | None = None,
        cost_details: dict[str, float] | None = None,
    ) -> None:
        try:
            self.client.record_observation(
                observation=self.sdk_observation,
                trace_id=self.trace_id,
                name=self.name,
                kind=self.kind,
                started_at=self.started_at,
                input=self.input,
                output=output,
                metadata={**self.metadata, **(metadata or {})},
                model=self.model,
                level=level or self.level,
                status_message=status_message or self.status_message,
                usage_details=usage_details,
                cost_details=cost_details,
            )
        finally:
            self.client._pop_observation(self.stack_token)
            self.stack_token = None


class LangfuseTracer:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.enabled = self.settings.langfuse_is_configured
        self.client = None
        if not self.enabled:
            return
        try:
            from langfuse import Langfuse

            self.client = Langfuse(
                public_key=self.settings.langfuse_public_key,
                secret_key=self.settings.langfuse_secret_key,
                host=self.settings.langfuse_host,
            )
        except Exception as exc:  # pragma: no cover - optional dependency safety
            self.enabled = False
            logger.warning("Langfuse initialization failed: %s", exc)

    def should_sample(self) -> bool:
        if not self.enabled:
            return False
        rate = self.settings.langfuse_effective_sample_rate
        return rate >= 1.0 or random.random() < rate

    @contextmanager
    def bind_trace(self, trace_id: str):
        # StreamingResponse generators may resume in a different execution context
        # than the one that created the ContextVar token, so avoid token.reset here.
        normalized_trace_id = _normalize_trace_id(trace_id)
        _current_trace_id.set(
            normalized_trace_id if self.enabled and normalized_trace_id else ""
        )
        try:
            yield
        finally:
            _current_trace_id.set("")

    @contextmanager
    def trace_chat_turn(
        self,
        *,
        trace_id: str,
        name: str,
        user_id: str,
        session_id: str,
        input: Any,
        metadata: dict[str, Any],
    ):
        normalized_trace_id = _normalize_trace_id(trace_id)
        token = _current_trace_id.set(
            normalized_trace_id if self.should_sample() else ""
        )
        root_token = _current_root_observation.set(None)
        stack_root_token = _current_observation_stack.set(())
        started_at = time.perf_counter()
        self._update_current_trace(
            name=name,
            user_id=user_id,
            session_id=session_id,
            input=input,
            output=None,
            metadata=metadata,
        )
        root_observation = self._start_sdk_observation(
            kind="span",
            name=name,
            input=input,
            metadata=metadata,
        )
        root_stack_token = self._push_observation(root_observation)
        _current_root_observation.set(root_observation)
        self._update_trace_from_observation(
            root_observation,
            name=name,
            user_id=user_id,
            session_id=session_id,
            input=input,
            output=None,
            metadata=metadata,
        )
        try:
            yield
        except Exception as exc:
            self.record_trace(
                trace_id=normalized_trace_id,
                name=name,
                user_id=user_id,
                session_id=session_id,
                input=input,
                output=None,
                metadata={**metadata, "duration_ms": _duration_ms(started_at)},
                level="ERROR",
                status_message=str(exc),
            )
            raise
        finally:
            self._end_sdk_observation(root_observation)
            self._pop_observation(root_stack_token)
            _current_observation_stack.reset(stack_root_token)
            _current_root_observation.reset(root_token)
            _current_trace_id.reset(token)

    def finalize_chat_turn(
        self,
        *,
        trace_id: str,
        name: str,
        user_id: str,
        session_id: str,
        input: Any,
        output: Any,
        metadata: dict[str, Any],
        started_at: float | None = None,
    ) -> None:
        self.record_trace(
            trace_id=_normalize_trace_id(trace_id),
            name=name,
            user_id=user_id,
            session_id=session_id,
            input=input,
            output=output,
            metadata=metadata
            if started_at is None
            else {**metadata, "duration_ms": _duration_ms(started_at)},
        )

    def start_span(
        self,
        name: str,
        *,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
        parent_observation: "LangfuseObservation | None" = None,
    ) -> LangfuseObservation:
        sdk_observation = self._start_sdk_observation(
            kind="span",
            name=name,
            input=input,
            metadata=metadata or {},
            trace_id=trace_id,
            parent_observation=(
                parent_observation.sdk_observation if parent_observation else None
            ),
        )
        return LangfuseObservation(
            client=self,
            name=name,
            kind="span",
            input=input,
            metadata=metadata or {},
            sdk_observation=sdk_observation,
            stack_token=self._push_observation(sdk_observation),
            trace_id=_normalize_trace_id(trace_id or _current_trace_id.get()),
            observation_id=str(getattr(sdk_observation, "id", "") or ""),
        )

    def start_workflow_node_span(
        self,
        *,
        node_name: str,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
        parent_observation: "LangfuseObservation | None" = None,
    ) -> LangfuseObservation:
        return self.start_span(
            workflow_span_name(node_name),
            input=input,
            metadata={
                "node": node_name,
                "span_name": workflow_span_name(node_name),
                "component": "chat_workflow",
                **(metadata or {}),
            },
            trace_id=trace_id,
            parent_observation=parent_observation,
        )

    def start_stream_compose_span(
        self,
        *,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
        parent_observation: "LangfuseObservation | None" = None,
    ) -> LangfuseObservation:
        return self.start_workflow_node_span(
            node_name="compose_answer",
            input=input,
            metadata={
                "component": "chat_stream",
                **(metadata or {}),
            },
            trace_id=trace_id,
            parent_observation=parent_observation,
        )

    def start_retrieval_span(
        self,
        *,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
        parent_observation: "LangfuseObservation | None" = None,
    ) -> LangfuseObservation:
        return self.start_span(
            "rag.retrieval",
            input=input,
            metadata=metadata or {},
            trace_id=trace_id,
            parent_observation=parent_observation,
        )

    def start_rerank_span(
        self,
        *,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
        parent_observation: "LangfuseObservation | None" = None,
    ) -> LangfuseObservation:
        return self.start_span(
            "rag.rerank",
            input=input,
            metadata=metadata or {},
            trace_id=trace_id,
            parent_observation=parent_observation,
        )

    def start_generation(
        self,
        name: str,
        *,
        model: str,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
        parent_observation: "LangfuseObservation | None" = None,
    ) -> LangfuseObservation:
        sdk_observation = self._start_sdk_observation(
            kind="generation",
            name=name,
            input=input,
            metadata=metadata or {},
            model=model,
            trace_id=trace_id,
            parent_observation=(
                parent_observation.sdk_observation if parent_observation else None
            ),
        )
        return LangfuseObservation(
            client=self,
            name=name,
            kind="generation",
            input=input,
            metadata=metadata or {},
            model=model,
            sdk_observation=sdk_observation,
            stack_token=self._push_observation(sdk_observation),
            trace_id=_normalize_trace_id(trace_id or _current_trace_id.get()),
            observation_id=str(getattr(sdk_observation, "id", "") or ""),
        )

    def start_answer_generation(
        self,
        *,
        model: str,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
        parent_observation: "LangfuseObservation | None" = None,
    ) -> LangfuseObservation:
        return self.start_generation(
            "llm.answer_generation",
            model=model,
            input=input,
            metadata=metadata or {},
            trace_id=trace_id,
            parent_observation=parent_observation,
        )

    def record_trace(
        self,
        *,
        trace_id: str,
        name: str,
        user_id: str,
        session_id: str,
        input: Any,
        output: Any,
        metadata: dict[str, Any],
        level: str = "DEFAULT",
        status_message: str = "",
    ) -> None:
        trace_id = _normalize_trace_id(trace_id)
        if not self.enabled or not trace_id:
            return
        payload = {
            "name": name,
            "user_id": user_id,
            "session_id": session_id,
            "metadata": _safe_payload(metadata),
        }
        if self.settings.langfuse_capture_input_output:
            payload["input"] = _safe_payload(input)
            payload["output"] = _safe_payload(output)
        if level != "DEFAULT":
            payload["level"] = level
        if status_message:
            payload["status_message"] = status_message
        root_observation = _current_root_observation.get()
        if root_observation is not None:
            self._update_trace_from_observation(root_observation, **payload)
            return
        with self.bind_trace(trace_id):
            self._call_client("update_current_trace", **payload)

    def record_observation(
        self,
        *,
        observation: Any = None,
        trace_id: str = "",
        name: str,
        kind: str,
        started_at: float,
        input: Any,
        output: Any,
        metadata: dict[str, Any],
        model: str = "",
        level: str = "DEFAULT",
        status_message: str = "",
        usage_details: dict[str, int] | None = None,
        cost_details: dict[str, float] | None = None,
    ) -> None:
        trace_id = _normalize_trace_id(trace_id or _current_trace_id.get())
        if not self.enabled or not trace_id:
            return
        payload = {
            "trace_id": trace_id,
            "name": name,
            "metadata": _safe_payload(
                {**metadata, "duration_ms": _duration_ms(started_at)}
            ),
        }
        if self.settings.langfuse_capture_input_output:
            payload["input"] = _safe_payload(input)
            payload["output"] = _safe_payload(output)
        if model:
            payload["model"] = model
        if usage_details:
            payload["usage_details"] = _safe_payload(usage_details)
        if cost_details:
            payload["cost_details"] = _safe_payload(cost_details)
        if level != "DEFAULT":
            payload["level"] = level
        if status_message:
            payload["status_message"] = status_message

        if observation is not None:
            self._update_sdk_observation(observation, **payload)
            return

        sdk_observation = self._start_sdk_observation(
            kind=kind,
            name=name,
            input=payload.get("input"),
            output=payload.get("output"),
            metadata=payload.get("metadata"),
            model=model,
            level=payload.get("level"),
            status_message=payload.get("status_message"),
        )
        if sdk_observation is not None:
            self._end_sdk_observation(sdk_observation)

    def score(
        self,
        *,
        trace_id: str,
        name: str,
        value: float,
        comment: str = "",
    ) -> None:
        trace_id = _normalize_trace_id(trace_id)
        if not self.enabled or not trace_id:
            return
        payload = {
            "trace_id": trace_id,
            "name": name,
            "value": value,
            "data_type": "NUMERIC",
        }
        if comment:
            payload["comment"] = comment
        self._call_client("create_score", **payload)

    def score_human_review_decision(
        self,
        *,
        trace_id: str,
        value: float,
        comment: str = "",
    ) -> None:
        self.score(
            trace_id=trace_id,
            name="human_review_decision",
            value=value,
            comment=comment,
        )

    def get_trace_url(self, *, trace_id: str) -> str | None:
        normalized_trace_id = _normalize_trace_id(trace_id)
        if not self.enabled or not normalized_trace_id or self.client is None:
            return None
        try:
            return self.client.get_trace_url(trace_id=normalized_trace_id)
        except Exception as exc:  # pragma: no cover - defensive by design
            logger.warning("Langfuse get_trace_url failed: %s", exc)
            return None

    def flush(self) -> None:
        if self.enabled:
            self._call_client("flush")

    def _call_client(self, method_name: str, **kwargs) -> None:
        if self.client is None:
            return
        try:
            method = getattr(self.client, method_name, None)
            if method is None:
                return
            method(**kwargs)
        except Exception as exc:  # pragma: no cover - defensive by design
            logger.warning("Langfuse %s failed: %s", method_name, exc)

    def _start_sdk_observation(
        self,
        *,
        kind: str,
        name: str,
        input: Any = None,
        output: Any = None,
        metadata: dict[str, Any] | None = None,
        model: str = "",
        level: str | None = None,
        status_message: str | None = None,
        trace_id: str | None = None,
        parent_observation: Any = None,
    ) -> Any:
        trace_id = _normalize_trace_id(trace_id or _current_trace_id.get())
        if not self.enabled or not trace_id or self.client is None:
            return None

        resolved_parent_observation = parent_observation or self._current_parent_observation()
        payload = {"name": name, "metadata": _safe_payload(metadata or {})}
        if self.settings.langfuse_capture_input_output:
            payload["input"] = _safe_payload(input)
            payload["output"] = _safe_payload(output)
        if level:
            payload["level"] = level
        if status_message:
            payload["status_message"] = status_message
        if kind == "generation" and model:
            payload["model"] = model

        method_name = "start_generation" if kind == "generation" else "start_span"
        try:
            if resolved_parent_observation is not None:
                method = getattr(resolved_parent_observation, method_name, None)
                if method is None:
                    return None
                return method(**payload)

            payload["trace_context"] = {"trace_id": trace_id}
            method = getattr(self.client, method_name, None)
            if method is None:
                return None
            return method(**payload)
        except Exception as exc:  # pragma: no cover - defensive by design
            logger.warning("Langfuse %s failed: %s", method_name, exc)
            return None

    def _update_sdk_observation(self, observation: Any, **payload) -> None:
        try:
            update = getattr(observation, "update", None)
            if update is not None:
                clean_payload = {
                    key: value
                    for key, value in payload.items()
                    if key not in {"trace_id"} and value is not None
                }
                update(**clean_payload)
            self._end_sdk_observation(observation)
        except Exception as exc:  # pragma: no cover - defensive by design
            logger.warning("Langfuse observation update failed: %s", exc)

    def _update_trace_from_observation(self, observation: Any, **payload) -> None:
        if observation is None:
            return
        try:
            update_trace = getattr(observation, "update_trace", None)
            if update_trace is None:
                return
            clean_payload = {
                key: value
                for key, value in payload.items()
                if key not in {"trace_id", "level", "status_message"}
                and value is not None
            }
            update_trace(**clean_payload)
        except Exception as exc:  # pragma: no cover - defensive by design
            logger.warning("Langfuse trace update failed: %s", exc)

    def _end_sdk_observation(self, observation: Any) -> None:
        try:
            end = getattr(observation, "end", None)
            if end is not None:
                end()
        except Exception as exc:  # pragma: no cover - defensive by design
            logger.warning("Langfuse observation end failed: %s", exc)

    def _update_current_trace(
        self,
        *,
        name: str,
        user_id: str,
        session_id: str,
        input: Any,
        output: Any,
        metadata: dict[str, Any],
        level: str = "DEFAULT",
        status_message: str = "",
    ) -> None:
        trace_id = _current_trace_id.get()
        if not self.enabled or not trace_id:
            return
        payload = {
            "name": name,
            "user_id": user_id,
            "session_id": session_id,
            "metadata": _safe_payload(metadata),
        }
        if self.settings.langfuse_capture_input_output:
            payload["input"] = _safe_payload(input)
            payload["output"] = _safe_payload(output)
        if level != "DEFAULT":
            payload["level"] = level
        if status_message:
            payload["status_message"] = status_message
        self._call_client("update_current_trace", **payload)

    def _current_parent_observation(self) -> Any:
        stack = _current_observation_stack.get()
        if not stack:
            return None
        return stack[-1]

    def _push_observation(self, observation: Any) -> Any:
        if observation is None:
            return None
        stack = _current_observation_stack.get()
        return _current_observation_stack.set((*stack, observation))

    def _pop_observation(self, token: Any) -> None:
        if token is None:
            return
        try:
            _current_observation_stack.reset(token)
        except Exception as exc:  # pragma: no cover - defensive by design
            logger.warning("Langfuse observation stack reset failed: %s", exc)


def _duration_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


@lru_cache
def get_langfuse_tracer() -> LangfuseTracer:
    return LangfuseTracer()


def current_trace_id() -> str:
    return _current_trace_id.get()
