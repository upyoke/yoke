"""Function handlers for decision requests and the per-actor Inbox."""

from __future__ import annotations

from typing import Optional

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.handlers.inbox_decision_models import (
    DecisionCreateRequest,
    DecisionMutationResponse,
    DecisionResolveRequest,
    DecisionRoleAuthority,
    DecisionWithdrawRequest,
    InboxListRequest,
    InboxListResponse,
)


def _error(
    code: str,
    message: str,
    *,
    jsonpath: Optional[str] = None,
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _require_global(
    request: FunctionCallRequest,
    function_id: str,
) -> Optional[HandlerOutcome]:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            f"{function_id} requires target.kind='global'",
            jsonpath="$.target.kind",
        )
    return None


def _actor_id(request: FunctionCallRequest, function_id: str) -> int | HandlerOutcome:
    raw = (request.actor.actor_id or "").strip()
    if not raw.isdigit():
        return _error("actor_required", f"{function_id} requires a bound numeric actor")
    return int(raw)


def handle_inbox_list(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = _require_global(request, "inbox.list")
    if invalid is not None:
        return invalid
    actor_id = _actor_id(request, "inbox.list")
    if isinstance(actor_id, HandlerOutcome):
        return actor_id
    payload = request.payload or {}
    project_ids = payload.get("project_ids")
    if project_ids is not None and (
        not isinstance(project_ids, list)
        or any(not isinstance(value, int) for value in project_ids)
    ):
        return _error(
            "payload_invalid",
            "project_ids must be an array of integers",
            jsonpath="$.payload.project_ids",
        )
    from yoke_core.domain import db_helpers
    from yoke_core.domain.inbox_read import inbox_for_actor

    conn = db_helpers.connect()
    try:
        result = inbox_for_actor(
            conn,
            actor_id=actor_id,
            project_ids=project_ids,
            include_read=bool(payload.get("include_read")),
        )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload=result,
        primary_success=True,
    )


def handle_decision_create(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = _require_global(request, "decision_requests.create")
    if invalid is not None:
        return invalid
    payload = request.payload or {}
    try:
        model = DecisionCreateRequest.model_validate(payload)
    except Exception as exc:  # Pydantic renders the exact invalid field
        return _error("payload_invalid", str(exc), jsonpath="$.payload")
    from yoke_core.domain import db_helpers
    from yoke_core.domain.decision_requests import (
        RoleAuthority,
        create_decision_request,
    )

    conn = db_helpers.connect()
    try:
        row, created = create_decision_request(
            conn,
            kind=model.kind,
            subject_type=model.subject_type,
            subject_key=model.subject_key,
            project_id=model.project_id,
            org_id=model.org_id,
            originator_actor_id=(
                model.originator_actor_id
                if model.originator_actor_id is not None
                else (
                    int(request.actor.actor_id)
                    if (request.actor.actor_id or "").isdigit()
                    else None
                )
            ),
            role_authorities=[
                RoleAuthority(value.scope_kind, value.scope_id, value.role_name)
                for value in model.role_authorities
            ],
            named_actor_ids=model.named_actor_ids,
            subject_context=model.subject_context,
            session_id=request.actor.session_id,
        )
    except (LookupError, ValueError) as exc:
        conn.rollback()
        return _error("payload_invalid", str(exc), jsonpath="$.payload")
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"request": row, "created": created},
        primary_success=True,
    )


def handle_decision_resolve(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = _require_global(request, "decision_requests.resolve")
    if invalid is not None:
        return invalid
    actor_id = _actor_id(request, "decision_requests.resolve")
    if isinstance(actor_id, HandlerOutcome):
        return actor_id
    try:
        model = DecisionResolveRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", str(exc), jsonpath="$.payload")
    from yoke_core.domain import db_helpers
    from yoke_core.domain.decision_request_resolution import (
        resolve_decision_request,
    )

    conn = db_helpers.connect()
    try:
        row = resolve_decision_request(
            conn,
            model.request_id,
            actor_id=actor_id,
            action=model.action,
            note=model.note,
            session_id=request.actor.session_id,
        )
    except LookupError as exc:
        conn.rollback()
        return _error("not_found", str(exc))
    except PermissionError as exc:
        conn.rollback()
        return _error("permission_denied", str(exc))
    except ValueError as exc:
        conn.rollback()
        return _error("invalid_state", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"request": row},
        primary_success=True,
    )


def handle_decision_withdraw(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = _require_global(request, "decision_requests.withdraw")
    if invalid is not None:
        return invalid
    actor_id = _actor_id(request, "decision_requests.withdraw")
    if isinstance(actor_id, HandlerOutcome):
        return actor_id
    try:
        model = DecisionWithdrawRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", str(exc), jsonpath="$.payload")
    from yoke_core.domain import db_helpers
    from yoke_core.domain.decision_request_resolution import (
        withdraw_decision_request,
    )

    conn = db_helpers.connect()
    try:
        row = withdraw_decision_request(
            conn,
            model.request_id,
            reason=model.reason,
            actor_id=actor_id,
            session_id=request.actor.session_id,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        conn.rollback()
        code = (
            "permission_denied" if isinstance(exc, PermissionError) else "invalid_state"
        )
        if isinstance(exc, LookupError):
            code = "not_found"
        return _error(code, str(exc))
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"request": row},
        primary_success=True,
    )


__all__ = [
    "DecisionCreateRequest",
    "DecisionMutationResponse",
    "DecisionResolveRequest",
    "DecisionRoleAuthority",
    "DecisionWithdrawRequest",
    "InboxListRequest",
    "InboxListResponse",
    "handle_decision_create",
    "handle_decision_resolve",
    "handle_decision_withdraw",
    "handle_inbox_list",
]
