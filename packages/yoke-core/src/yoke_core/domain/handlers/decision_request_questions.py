"""Session-scoped filing and history for operator questions."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.qa_artifact_storage import ArtifactStorageError
from yoke_core.domain.handlers.inbox_decisions import _actor_id, _error, _require_global


class QuestionAskRequest(BaseModel):
    requesting_session_id: str | None = None
    key: str
    question: str
    context: str = ""
    options: list[dict[str, Any]] = Field(default_factory=list)
    recommended_option: str | None = None
    allow_freeform: bool = True
    item: str | None = None
    to: list[str] = Field(default_factory=list)
    audience: str | None = None
    project: str | None = None
    replaces: int | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class QuestionListRequest(BaseModel):
    requesting_session_id: str | None = None
    status: str | None = None


class QuestionListResponse(BaseModel):
    questions: list[dict[str, Any]]


def _session(conn, request, session_id, actor_id):
    from yoke_core.domain.decision_requests import _p
    from yoke_core.domain.session_steering_authority import covering_session_seat

    row = conn.execute(
        f"SELECT * FROM harness_sessions WHERE session_id={_p(conn)}",
        (session_id,),
    ).fetchone()
    if row is None:
        raise ValueError(
            "operator_question_session_missing: start a registered session and retry"
        )
    target = dict(row)
    if target.get("actor_id") != actor_id:
        if not covering_session_seat(
            conn, caller_session_id=request.actor.session_id, target=target
        ):
            raise PermissionError(
                "operator_question_session_forbidden: ask the session's steering seat to file or read this question"
            )
    return target


def _handle(request, model_type, operation):
    invalid = _require_global(request, request.function)
    if invalid is not None:
        return invalid
    actor_id = _actor_id(request, request.function)
    if isinstance(actor_id, HandlerOutcome):
        return actor_id
    from yoke_core.domain.db_helpers import connect

    try:
        model = model_type.model_validate(request.payload or {})
        session_id = model.requesting_session_id or request.actor.session_id
        with connect() as conn:
            session = _session(conn, request, session_id, actor_id)
            result = operation(conn, model, session, actor_id)
    except ArtifactStorageError as exc:
        return _error(
            "operator_question_attachment_store_failed",
            f"{exc}; repair the QA evidence store and retry ask --attach PATH",
        )
    except (LookupError, ValueError, PermissionError) as exc:
        return _error(
            "permission_denied"
            if isinstance(exc, PermissionError)
            else "operator_question_invalid",
            str(exc),
        )
    return HandlerOutcome(primary_success=True, result_payload=result)


def handle_ask(request: FunctionCallRequest) -> HandlerOutcome:
    def file(conn, model, session, actor_id):
        from yoke_core.domain.decision_request_question_filing import file_question
        from yoke_core.domain.decision_request_question_target import question_target

        target = question_target(conn, model, session, actor_id)
        context = model.model_dump(
            exclude={
                "requesting_session_id",
                "key",
                "item",
                "replaces",
                "attachments",
                "to",
                "audience",
                "project",
            }
        )
        item_id = target.pop("item_id")
        if item_id is not None:
            context["item_id"] = item_id
        row, created = file_question(
            conn,
            replaces=model.replaces,
            attachments=model.attachments,
            kind="operator_question",
            subject_type="session_question",
            subject_key=f"{session['session_id']}:{model.key}",
            **target,
            requesting_session_id=session["session_id"],
            originator_actor_id=actor_id,
            subject_context=context,
            session_id=request.actor.session_id,
        )
        return {"request": row, "created": created}

    return _handle(request, QuestionAskRequest, file)


def handle_list(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.decision_request_question_filing import list_questions

    return _handle(
        request,
        QuestionListRequest,
        lambda conn, model, session, actor: {
            "questions": list_questions(conn, session["session_id"], model.status),
        },
    )


def register(registry):
    from yoke_core.domain.handlers.inbox_decision_models import DecisionMutationResponse

    for function_id, handler, request_model, response_model, effects in (
        (
            "decision_requests.ask",
            handle_ask,
            QuestionAskRequest,
            DecisionMutationResponse,
            ["decision_requests_insert"],
        ),
        (
            "decision_requests.list",
            handle_list,
            QuestionListRequest,
            QuestionListResponse,
            [],
        ),
    ):
        registry.register(
            function_id,
            handler,
            request_model,
            response_model,
            stability="stable",
            owner_module=__name__,
            target_kinds=["global"],
            side_effects=effects,
            emitted_event_names=["DecisionRequestCreated"] if effects else [],
            guardrails=["actor_required", "session_scope"],
            adapter_status="live",
            claim_required_kind=None,
            ambient_session_required=False,
            minimum_serving_version="next-release",
        )
