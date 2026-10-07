"""End a pending machine approval on an expired or withdrawn observation.

Two authorities may end one. The request's own role authority (the org
admin) may withdraw it whatever the hosted service says. The hosted service's
own identity may end it without that authority, but only once the engine's
own record shows the authorization has ended: the end evidence stored when
the request was opened, read before this delivery's claimed status is written
and against the engine's clock rather than the delivery's ``occurred_at``. A
service delivery about a live authorization is refused by name.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.decision_request_resolution import (
    withdraw_decision_request,
    withdraw_for_ended_subject,
)
from yoke_core.domain.decision_request_subject_state import (
    require_decision_request_subject_ended,
)
from yoke_core.domain.hosted_service_authority import hosted_service_org_ids


def _record_terminal_context(
    conn: Any,
    request: Mapping[str, Any],
    *,
    status: str,
    observed_at: str,
    reason: str,
) -> None:
    context = request.get("subject_context")
    updated = dict(context) if isinstance(context, Mapping) else {}
    updated["status"] = status
    updated[f"{status}_at"] = observed_at
    updated["reason"] = reason
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        f"UPDATE decision_requests SET subject_context = {p} WHERE id = {p}",
        (json.dumps(updated, separators=(",", ":")), int(request["id"])),
    )


def _require_recorded_end(conn: Any, request: Mapping[str, Any], state: str) -> None:
    """Refuse a service delivery the engine's own record does not show ended."""
    try:
        require_decision_request_subject_ended(conn, request, observed_at=iso8601_now())
    except ValueError as exc:
        raise PermissionError(
            f"hosted_service_withdrawal_subject_live: the hosted service "
            f"reported machine authorization {request.get('subject_key')} "
            f"{state}, but this universe's own record shows it has not ended "
            f"({exc}). The hosted service may end only an authorization whose "
            "stored expiry has passed; an org admin withdraws a live one, or "
            "redeliver after the stored expiry"
        ) from exc


def withdraw_machine_approval(
    conn: Any,
    request: Mapping[str, Any],
    *,
    org_id: int,
    state: str,
    occurred_at: str,
    actor_id: int,
    reason: Optional[str],
    session_id: str,
    opened_by_this_delivery: bool,
) -> dict[str, Any]:
    """Record the terminal observation and withdraw under the right authority.

    A request this same delivery opened carried no prior live approval, so
    there is nothing a false claim could cancel and no stored evidence to read.
    """
    service = int(org_id) in hosted_service_org_ids(conn, actor_id)
    if service and not opened_by_this_delivery:
        _require_recorded_end(conn, request, state)
    withdrawal_reason = (reason or f"machine authorization {state}").strip()
    _record_terminal_context(
        conn,
        request,
        status=state,
        observed_at=occurred_at,
        reason=withdrawal_reason,
    )
    withdraw = withdraw_for_ended_subject if service else withdraw_decision_request
    return withdraw(
        conn,
        int(request["id"]),
        reason=withdrawal_reason,
        actor_id=actor_id,
        session_id=session_id,
        withdrawn_at=occurred_at,
    )


__all__ = ["withdraw_machine_approval"]
