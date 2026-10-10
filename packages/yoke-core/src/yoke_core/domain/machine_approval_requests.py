"""Decision-request adapter for a hosted machine authorization."""

from __future__ import annotations

from datetime import datetime
from typing import Any, get_args, Literal, Mapping, Optional

from yoke_contracts.timestamps import format_instant, parse_instant, utc_now
from yoke_core.domain.decision_machine_clocks import machine_context_wire

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import db_backend
from yoke_core.domain.decision_request_contract import MACHINE_APPROVAL
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.decision_request_subject_state import (
    _instant,
    _MACHINE_END_TIMESTAMPS,
    _MACHINE_ENDED_STATES,
)
from yoke_core.domain.machine_approval_withdrawal import withdraw_machine_approval
from yoke_core.domain.decision_requests import (
    RoleAuthority,
    create_decision_request,
    list_subject_requests,
)


MACHINE_AUTH_SUBJECT = "machine_auth_request"
MachineApprovalLifecycleStatus = Literal[
    "pending",
    "approved",
    "denied",
    "expired",
    "withdrawn",
]
MACHINE_APPROVAL_LIFECYCLE_STATES = frozenset(get_args(MachineApprovalLifecycleStatus))
_RESOLUTION_ACTIONS = {"approved": "approve", "denied": "deny"}
_WITHDRAWAL_STATES = frozenset({"expired", "withdrawn"})


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _matching_request(
    history: list[dict[str, Any]],
    org_id: int,
) -> Optional[dict[str, Any]]:
    return next(
        (row for row in history if int(row.get("org_id") or 0) == int(org_id)),
        None,
    )


def _withdrawn_by_expiry(context: Mapping[str, Any], withdrawn_at: Any) -> bool:
    """Replay the disposal sweep's own expiry-vs-other-cause precedence so a
    later ``expired`` delivery converges instead of colliding with the
    generic ``withdrawn`` write that sweep made without stamping context.
    """
    state = str(context.get("status") or context.get("state") or "").lower()
    observed = _instant(withdrawn_at)
    if state in _MACHINE_ENDED_STATES or observed is None:
        return False
    if any(
        (instant := _instant(context.get(key))) is not None and instant <= observed
        for key in _MACHINE_END_TIMESTAMPS
    ):
        return False
    expires_at = _instant(context.get("expires_at"))
    return expires_at is not None and expires_at <= observed


def _terminal_state(request: Mapping[str, Any]) -> Optional[str]:
    if request.get("status") == "resolved":
        action = str(request.get("resolution_action") or "")
        return {"approve": "approved", "deny": "denied"}.get(action)
    if request.get("status") == "withdrawn":
        context = request.get("subject_context")
        context = context if isinstance(context, Mapping) else {}
        state = str(context.get("status") or "").lower()
        if state in _WITHDRAWAL_STATES:
            return state
        if _withdrawn_by_expiry(context, request.get("withdrawn_at")):
            return "expired"
        return "withdrawn"
    return None


def ensure_machine_approval(
    conn: Any,
    *,
    auth_request_id: str,
    org_id: int,
    context: Mapping[str, Any],
    originator_actor_id: Optional[int] = None,
    session_id: str = "",
    created_at: datetime | str | None = None,
    self_approval_actor_id: Optional[int] = None,
) -> tuple[dict[str, Any], bool]:
    """Record an org-admin approval, or a named user approving their own machine."""
    stamp = parse_instant(created_at) if created_at is not None else utc_now()
    context = machine_context_wire(context)
    history = list_subject_requests(
        conn,
        MACHINE_AUTH_SUBJECT,
        auth_request_id,
    )
    matching = _matching_request(history, org_id)
    if matching and matching["status"] in {"pending", "resolved"}:
        return matching, False
    return create_decision_request(
        conn,
        kind=MACHINE_APPROVAL,
        subject_type=MACHINE_AUTH_SUBJECT,
        subject_key=auth_request_id,
        org_id=int(org_id),
        originator_actor_id=originator_actor_id,
        role_authorities=[]
        if self_approval_actor_id
        else [RoleAuthority("org", int(org_id), "admin")],
        named_actor_ids=[self_approval_actor_id] if self_approval_actor_id else [],
        subject_context=dict(context),
        session_id=session_id,
        created_at=stamp,
    )


def apply_machine_approval_lifecycle(
    conn: Any,
    *,
    auth_request_id: str,
    org_id: int,
    state: str,
    occurred_at: datetime | str,
    actor_id: int,
    context: Mapping[str, Any],
    reason: Optional[str] = None,
    session_id: str = "",
) -> tuple[Optional[dict[str, Any]], bool, bool]:
    """Apply one hosted authorization state without duplicating decisions."""
    occurred_at = parse_instant(occurred_at)
    context = machine_context_wire(context)
    state = str(state).strip().lower()
    if state not in MACHINE_APPROVAL_LIFECYCLE_STATES:
        raise ValueError(f"unsupported machine authorization state {state!r}")
    history = list_subject_requests(conn, MACHINE_AUTH_SUBJECT, auth_request_id)
    request = _matching_request(history, org_id)

    existing_terminal = _terminal_state(request or {})
    if existing_terminal is not None:
        if existing_terminal == state:
            return request, False, False
        raise ValueError(
            f"machine authorization {auth_request_id} is already "
            f"{existing_terminal}, not {state}"
        )
    other_live = next(
        (
            row
            for row in history
            if int(row.get("org_id") or 0) != int(org_id)
            and row.get("status") in {"pending", "resolved"}
        ),
        None,
    )
    if other_live is not None:
        raise ValueError(
            f"machine authorization {auth_request_id} is bound to "
            f"organization {other_live['org_id']}"
        )

    created = False
    if request is None:
        initial_context = dict(context)
        initial_context["status"] = "pending" if state == "pending" else state
        initial_context["occurred_at"] = format_instant(occurred_at)
        request, created = ensure_machine_approval(
            conn,
            auth_request_id=auth_request_id,
            org_id=org_id,
            context=initial_context,
            originator_actor_id=actor_id,
            session_id=session_id,
            created_at=occurred_at,
        )
    if state == "pending":
        return request, created, created
    if state in _RESOLUTION_ACTIONS:
        resolved = resolve_decision_request(
            conn,
            int(request["id"]),
            actor_id=actor_id,
            action=_RESOLUTION_ACTIONS[state],
            note=reason,
            session_id=session_id,
            resolved_at=occurred_at,
        )
        return resolved, created, True

    return (
        withdraw_machine_approval(
            conn,
            request,
            org_id=org_id,
            state=state,
            occurred_at=occurred_at,
            actor_id=actor_id,
            reason=reason,
            session_id=session_id,
            opened_by_this_delivery=created,
        ),
        created,
        True,
    )


def apply_machine_approval_lifecycle_request(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Apply one Platform authorization delivery through the function surface."""
    function_id = "machine_approval.lifecycle.apply"
    if request.target.kind != "global":
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="target_invalid",
                message=f"{function_id} requires target.kind='global'",
                jsonpath="$.target.kind",
            ),
        )
    actor_text = str(request.actor.actor_id or "").strip()
    if not actor_text.isdigit():
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="actor_required",
                message=f"{function_id} requires a bound numeric actor",
            ),
        )
    from yoke_core.domain.handlers.inbox_decision_models import (
        MachineApprovalLifecycleRequest,
    )

    try:
        model = MachineApprovalLifecycleRequest.model_validate(request.payload or {})
    except Exception as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message=str(exc),
                jsonpath="$.payload",
            ),
        )
    context: dict[str, Any] = {}
    if model.expires_at is not None:
        context["expires_at"] = format_instant(model.expires_at)
    if model.code is not None:
        context["code"] = model.code
    if model.machine is not None:
        context["machine"] = model.machine
    from yoke_core.domain import db_helpers
    from yoke_core.domain.external_identities import (
        default_org_id,
        ExternalIdentityError,
    )

    conn = db_helpers.connect()
    try:
        org_id = default_org_id(conn)
        row, created, applied = apply_machine_approval_lifecycle(
            conn,
            auth_request_id=str(model.authorization_id),
            org_id=org_id,
            state=model.state,
            occurred_at=model.occurred_at,
            actor_id=int(actor_text),
            context=context,
            reason=model.reason,
            session_id=request.actor.session_id,
        )
    except (ExternalIdentityError, LookupError, PermissionError, ValueError) as exc:
        conn.rollback()
        code = "invalid_state"
        if isinstance(exc, (ExternalIdentityError, LookupError)):
            code = "not_found"
        elif isinstance(exc, PermissionError):
            code = "permission_denied"
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(code=code, message=str(exc)),
        )
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={
            "request": row,
            "created": created,
            "applied": applied,
        },
        primary_success=True,
    )


def machine_approval_decision(
    conn: Any,
    *,
    auth_request_id: str,
) -> Optional[str]:
    """Return ``approve``/``deny``, or ``None`` while waiting."""
    history = list_subject_requests(
        conn,
        MACHINE_AUTH_SUBJECT,
        auth_request_id,
    )
    if not history or history[0]["status"] != "resolved":
        return None
    action = history[0].get("resolution_action")
    return str(action) if action else None
