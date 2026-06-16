from langgraph.graph import END, START, StateGraph

from app.integrations.langfuse_tracing import get_langfuse_tracer
from app.workflows.chat_graph_clarification import (
    _clarification_confirm_switch,
    _clarification_current_topic,
    _clarification_freeform_current_topic,
    _clarification_freeform_defer,
    _clarification_freeform_new_topic,
    _clarification_freeform_router,
    _clarification_new_topic,
    _clarification_passthrough,
    _clarification_router,
    _intent_guard,
    _intake_question,
    _load_assistant_config,
    _manage_memory,
    _resolve_kb_scope,
    _route_after_clarification_freeform_router,
    _route_after_clarification_handler,
    _route_after_clarification_router,
    _route_after_intent_guard,
)
from app.workflows.chat_graph_execution import (
    _compose_answer,
    _retrieve_context,
    _review_gate,
    _review_hold,
    _route_after_review_gate,
    _route_after_review_hold,
)
from app.workflows.chat_graph_support import ChatWorkflowState

_WORKFLOW_NODES = (
    ("assistant_config", _load_assistant_config),
    ("kb_scope", _resolve_kb_scope),
    ("question_intake", _intake_question),
    ("memory_manager", _manage_memory),
    ("clarification_router", _clarification_router),
    ("clarification_passthrough", _clarification_passthrough),
    ("clarification_confirm_switch", _clarification_confirm_switch),
    ("clarification_current_topic", _clarification_current_topic),
    ("clarification_new_topic", _clarification_new_topic),
    ("clarification_freeform_router", _clarification_freeform_router),
    (
        "clarification_freeform_current_topic",
        _clarification_freeform_current_topic,
    ),
    ("clarification_freeform_new_topic", _clarification_freeform_new_topic),
    ("clarification_freeform_defer", _clarification_freeform_defer),
    ("intent_guard", _intent_guard),
    ("retrieve_context", _retrieve_context),
    ("review_gate", _review_gate),
    ("review_hold", _review_hold),
)

_CLARIFICATION_HANDLER_NODE_NAMES = (
    "clarification_passthrough",
    "clarification_confirm_switch",
    "clarification_current_topic",
    "clarification_new_topic",
    "clarification_freeform_current_topic",
    "clarification_freeform_new_topic",
    "clarification_freeform_defer",
)

_CLARIFICATION_ROUTE_TARGETS = {
    "clarification_passthrough": "clarification_passthrough",
    "clarification_confirm_switch": "clarification_confirm_switch",
    "clarification_current_topic": "clarification_current_topic",
    "clarification_new_topic": "clarification_new_topic",
    "clarification_freeform_router": "clarification_freeform_router",
}

_CLARIFICATION_FREEFORM_ROUTE_TARGETS = {
    "clarification_freeform_current_topic": "clarification_freeform_current_topic",
    "clarification_freeform_new_topic": "clarification_freeform_new_topic",
    "clarification_freeform_defer": "clarification_freeform_defer",
}

def _build_workflow_node_input(node_name: str, state: ChatWorkflowState) -> dict:
    return {
        "node": node_name,
        "assistant_id": state.get("assistant_id", ""),
        "assistant_name": state.get("assistant_name", ""),
        "question": state.get("question", ""),
        "resolved_question": state.get("resolved_question", ""),
        "effective_question": state.get("effective_question", ""),
        "current_goal": state.get("current_goal", ""),
        "question_control_action": state.get("question_control_action", ""),
        "selected_knowledge_base_id": state.get("selected_knowledge_base_id", ""),
        "selected_kb_ids": state.get("selected_kb_ids", []),
        "retrieval_count": state.get("retrieval_count", 0),
        "session_status": state.get("session_status", "active"),
        "clarification_type": state.get("clarification_type", ""),
        "clarification_stage": state.get("clarification_stage", ""),
        "clarification_reason": state.get("clarification_reason", ""),
        "review_reason": state.get("review_reason", ""),
        "intent_drift_score": state.get("intent_drift_score", 0.0),
        "fallback_reason": state.get("fallback_reason"),
    }


def _build_workflow_node_output(result: ChatWorkflowState) -> dict:
    payload = {
        "assistant_id": result.get("assistant_id", ""),
        "assistant_name": result.get("assistant_name", ""),
        "resolved_question": result.get("resolved_question", ""),
        "effective_question": result.get("effective_question", ""),
        "current_goal": result.get("current_goal", ""),
        "selected_knowledge_base_id": result.get("selected_knowledge_base_id", ""),
        "selected_kb_ids": result.get("selected_kb_ids", []),
        "clarification_route": result.get("clarification_route", ""),
        "clarification_action": result.get("clarification_action", ""),
        "clarification_freeform_route": result.get(
            "clarification_freeform_route",
            "",
        ),
        "clarification_type": result.get("clarification_type", ""),
        "clarification_stage": result.get("clarification_stage", ""),
        "clarification_reason": result.get("clarification_reason", ""),
        "intent_action": result.get("intent_action", ""),
        "intent_drift_score": result.get("intent_drift_score", 0.0),
        "review_reason": result.get("review_reason", ""),
        "review_decision": result.get("review_decision", ""),
        "fallback_reason": result.get("fallback_reason"),
        "retrieval_count": result.get("retrieval_count", 0),
        "citation_count": len(result.get("citations", [])),
        "has_answer": bool(str(result.get("answer", "")).strip()),
    }
    workflow_trace = list(result.get("workflow_trace", []))
    if workflow_trace:
        latest = workflow_trace[-1]
        payload["latest_trace_node"] = latest.node
        payload["latest_trace_detail"] = latest.detail
        payload["workflow_trace_count"] = len(workflow_trace)
    return payload


def _instrument_workflow_node(node_name: str, node_handler):
    def wrapped(state: ChatWorkflowState) -> ChatWorkflowState:
        span = get_langfuse_tracer().start_workflow_node_span(
            node_name=node_name,
            input=_build_workflow_node_input(node_name, state),
        )
        try:
            result = node_handler(state)
        except Exception as exc:
            span.end(level="ERROR", status_message=str(exc))
            raise
        span.end(output=_build_workflow_node_output(result))
        return result

    return wrapped


def _build_clarification_handler_targets(
    include_compose_answer: bool,
):
    targets = {
        "intent_guard": "intent_guard",
        "retrieve_context": "retrieve_context",
        "clarification_freeform_router": "clarification_freeform_router",
        "end": END,
    }
    if include_compose_answer:
        targets["compose_answer"] = "compose_answer"
    return targets


def _build_intent_guard_targets(include_compose_answer: bool):
    targets = {"retrieve_context": "retrieve_context"}
    if include_compose_answer:
        targets["compose_answer"] = "compose_answer"
    else:
        targets["end"] = END
    return targets


def _build_review_gate_targets(include_compose_answer: bool):
    targets = {"review_hold": "review_hold"}
    if include_compose_answer:
        targets["compose_answer"] = "compose_answer"
    else:
        targets["end"] = END
    return targets


def _build_review_hold_targets(include_compose_answer: bool):
    if include_compose_answer:
        return {
            "compose_answer": "compose_answer",
            "end": END,
        }
    return {"end": END}


def _register_workflow_nodes(
    builder: StateGraph,
    *,
    include_compose_answer: bool,
) -> None:
    for node_name, node_handler in _WORKFLOW_NODES:
        builder.add_node(node_name, _instrument_workflow_node(node_name, node_handler))
    if include_compose_answer:
        builder.add_node(
            "compose_answer",
            _instrument_workflow_node("compose_answer", _compose_answer),
        )


def _add_clarification_handler_edges(
    builder: StateGraph,
    *,
    include_compose_answer: bool,
) -> None:
    def route(state):
        return _route_after_clarification_handler(
            state,
            include_compose_answer=include_compose_answer,
        )

    targets = _build_clarification_handler_targets(include_compose_answer)
    for node_name in _CLARIFICATION_HANDLER_NODE_NAMES:
        builder.add_conditional_edges(node_name, route, targets)


def build_chat_workflow(
    *,
    include_compose_answer: bool,
    checkpointer=None,
):
    builder = StateGraph(ChatWorkflowState)

    def route_after_intent_guard(state):
        return _route_after_intent_guard(
            state,
            include_compose_answer=include_compose_answer,
        )

    def route_after_review_gate(state):
        return _route_after_review_gate(
            state,
            include_compose_answer=include_compose_answer,
        )

    def route_after_review_hold(state):
        return _route_after_review_hold(
            state,
            include_compose_answer=include_compose_answer,
        )

    _register_workflow_nodes(
        builder,
        include_compose_answer=include_compose_answer,
    )

    builder.add_edge(START, "assistant_config")
    builder.add_edge("assistant_config", "kb_scope")
    builder.add_edge("kb_scope", "question_intake")
    builder.add_edge("question_intake", "memory_manager")
    builder.add_edge("memory_manager", "clarification_router")
    builder.add_conditional_edges(
        "clarification_router",
        _route_after_clarification_router,
        _CLARIFICATION_ROUTE_TARGETS,
    )
    builder.add_conditional_edges(
        "clarification_freeform_router",
        _route_after_clarification_freeform_router,
        _CLARIFICATION_FREEFORM_ROUTE_TARGETS,
    )
    _add_clarification_handler_edges(
        builder,
        include_compose_answer=include_compose_answer,
    )
    builder.add_conditional_edges(
        "intent_guard",
        route_after_intent_guard,
        _build_intent_guard_targets(include_compose_answer),
    )
    builder.add_edge("retrieve_context", "review_gate")
    builder.add_conditional_edges(
        "review_gate",
        route_after_review_gate,
        _build_review_gate_targets(include_compose_answer),
    )
    builder.add_conditional_edges(
        "review_hold",
        route_after_review_hold,
        _build_review_hold_targets(include_compose_answer),
    )
    if include_compose_answer:
        builder.add_edge("compose_answer", END)
    return builder.compile(checkpointer=checkpointer)
