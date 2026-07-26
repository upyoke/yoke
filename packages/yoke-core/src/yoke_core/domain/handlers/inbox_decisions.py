"""Function handlers for decision requests and the per-actor Inbox."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class InboxListRequest(BaseModel):
    project_ids: Optional[List[int]] = None
    include_read: bool = False


class InboxListResponse(BaseModel):
    needs_decision: List[Dict[str, Any]]
    requests: List[Dict[str, Any]]
    notifications: List[Dict[str, Any]]


class DecisionRoleAuthority(BaseModel):
    scope_kind: str
    scope_id: int
    role_name: str


class DecisionCreateRequest(BaseModel):
    kind: str
    subject_type: str
    subject_key: str
    project_id: Optional[int] = None
    org_id: Optional[int] = None
    originator_actor_id: Optional[int] = None
    role_authorities: List[DecisionRoleAuthority] = Field(default_factory=list)
    named_actor_ids: List[int] = Field(default_factory=list)
    subject_context: Dict[str, Any] = Field(default_factory=dict)


class DecisionMutationResponse(BaseModel):
    request: Dict[str, Any]
    created: Optional[bool] = None


class DecisionResolveRequest(BaseModel):
    request_id: int
    action: str
    note: Optional[str] = None


class DecisionWithdrawRequest(BaseModel):
    request_id: int
    reason: str


class NotificationReadRequest(BaseModel):
    notification_id: int


class NotificationReadResponse(BaseModel):
    read: bool
    notification_id: Optional[int] = None
    count: Optional[int] = None


def _error(
    code: str, message: str, *, jsonpath: Optional[str] = None,
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _require_global(
    request: FunctionCallRequest, function_id: str,
) -> Optional[HandlerOutcome]:
    if request.target.kind != "global":
        return _error(
            "target_invalid", f"{function_id} requires target.kind='global'",
            jsonpath="$.target.kind",
        )
    return None


def _actor_id(
    request: FunctionCallRequest, function_id: str,
) -> int | HandlerOutcome:
    raw = (request.actor.actor_id or "").strip()
    if not raw.isdigit():
        return _error(
            "actor_required", f"{function_id} requires a bound numeric actor"
        )
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
            "payload_invalid", "project_ids must be an array of integers",
            jsonpath="$.payload.project_ids",
        )
    from yoke_core.domain import db_helpers
    from yoke_core.domain.decision_requests import pending_requests_for_actor
    from yoke_core.domain.inbox_notifications import notification_rows

    conn = db_helpers.connect()
    try:
        decisions = pending_requests_for_actor(
            conn, actor_id, project_ids=project_ids,
        )
        notifications = notification_rows(
            conn, actor_id, unread_only=not bool(payload.get("include_read")),
        )
        if project_ids is not None:
            allowed = set(project_ids)
            notifications = [
                row for row in notifications
                if row.get("project_id") is None
                or int(row["project_id"]) in allowed
            ]
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={
            "needs_decision": [row for row in decisions if row["blocking"]],
            "requests": [row for row in decisions if not row["blocking"]],
            "notifications": notifications,
        },
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
            conn, kind=model.kind, subject_type=model.subject_type,
            subject_key=model.subject_key, project_id=model.project_id,
            org_id=model.org_id,
            originator_actor_id=(
                model.originator_actor_id
                if model.originator_actor_id is not None
                else (
                    int(request.actor.actor_id)
                    if (request.actor.actor_id or "").isdigit() else None
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
            conn, model.request_id, actor_id=actor_id, action=model.action,
            note=model.note, session_id=request.actor.session_id,
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
        result_payload={"request": row}, primary_success=True,
    )


def handle_decision_withdraw(request: FunctionCallRequest) -> HandlerOutcome:
    invalid = _require_global(request, "decision_requests.withdraw")
    if invalid is not None:
        return invalid
    try:
        model = DecisionWithdrawRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", str(exc), jsonpath="$.payload")
    from yoke_core.domain import db_helpers
    from yoke_core.domain.decision_request_resolution import (
        withdraw_decision_request,
    )

    raw_actor = (request.actor.actor_id or "").strip()
    conn = db_helpers.connect()
    try:
        row = withdraw_decision_request(
            conn, model.request_id, reason=model.reason,
            actor_id=int(raw_actor) if raw_actor.isdigit() else None,
            session_id=request.actor.session_id,
        )
    except LookupError as exc:
        conn.rollback()
        return _error("not_found", str(exc))
    except ValueError as exc:
        conn.rollback()
        return _error("invalid_state", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"request": row}, primary_success=True,
    )


def _mark_read(
    request: FunctionCallRequest, *, all_rows: bool,
) -> HandlerOutcome:
    function_id = "notifications.read_all" if all_rows else "notifications.read"
    invalid = _require_global(request, function_id)
    if invalid is not None:
        return invalid
    actor_id = _actor_id(request, function_id)
    if isinstance(actor_id, HandlerOutcome):
        return actor_id
    model = None
    if not all_rows:
        try:
            model = NotificationReadRequest.model_validate(request.payload or {})
        except Exception as exc:
            return _error("payload_invalid", str(exc), jsonpath="$.payload")
    from yoke_core.domain import db_helpers
    from yoke_core.domain.decision_request_contract import NOTIFICATION_READ_EVENT
    from yoke_core.domain.decision_request_events import append_decision_event
    from yoke_core.domain.inbox_notifications import (
        mark_all_notifications_read,
        mark_notification_read,
    )

    stamp = db_helpers.iso8601_now()
    conn = db_helpers.connect()
    try:
        count = (
            mark_all_notifications_read(conn, actor_id, stamp)
            if all_rows else int(mark_notification_read(
                conn, actor_id, model.notification_id, stamp,
            ))
        )
        if count:
            append_decision_event(
                conn, NOTIFICATION_READ_EVENT, actor_id=actor_id,
                session_id=request.actor.session_id, project_id=None,
                org_id=None, context={
                    "notification_id": None if all_rows else model.notification_id,
                    "count": count,
                }, created_at=stamp,
            )
        conn.commit()
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={
            "read": bool(count),
            "notification_id": None if all_rows else model.notification_id,
            "count": count,
        },
        primary_success=True,
    )


def handle_notification_read(request: FunctionCallRequest) -> HandlerOutcome:
    return _mark_read(request, all_rows=False)


def handle_notifications_read_all(request: FunctionCallRequest) -> HandlerOutcome:
    return _mark_read(request, all_rows=True)


__all__ = [
    "DecisionCreateRequest",
    "DecisionMutationResponse",
    "DecisionResolveRequest",
    "DecisionWithdrawRequest",
    "InboxListRequest",
    "InboxListResponse",
    "NotificationReadRequest",
    "NotificationReadResponse",
    "handle_decision_create",
    "handle_decision_resolve",
    "handle_decision_withdraw",
    "handle_inbox_list",
    "handle_notification_read",
    "handle_notifications_read_all",
]
