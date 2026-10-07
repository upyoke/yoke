"""End a pending machine approval on an expired or withdrawn observation.

Two authorities may end one. The request's own role authority (the org
admin) may withdraw it whatever the hosted service says. The hosted service's
own identity may end it without that authority, but only once the engine's
own rows show the authorization has ended, read before this delivery's
claimed status is written: the expiry stored when the request opened has
passed by the engine's clock (never the delivery's ``occurred_at``), or the
requesting member is disabled or holds no role left in the org. A service
delivery about a live authorization is refused by name.
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
from yoke_core.domain.actor_state import actor_is_active
from yoke_core.domain.hosted_service_authority import (
    hosted_service_org_ids,
    is_hosted_service_actor,
)


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


def _member_departure(conn: Any, request_id: int, org_id: int) -> Optional[str]:
    """Name how the requesting member left ``org_id``, or ``None`` if they remain.

    Read from the request's stored originator and that actor's own rows,
    never from the delivery: a disabled actor, or one holding no org role and
    no project role in the org, can no longer be admitted to it.
    """
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT originator_actor_id FROM decision_requests WHERE id = {p}",
        (request_id,),
    ).fetchone()
    member = row[0] if row is not None else None
    if member is None or is_hosted_service_actor(conn, int(member)):
        return None
    member = int(member)
    if not actor_is_active(conn, member):
        return f"requesting actor {member} is disabled"
    org_role = conn.execute(
        f"SELECT 1 FROM actor_org_roles WHERE actor_id = {p} AND org_id = {p} LIMIT 1",
        (member, org_id),
    ).fetchone()
    project_role = conn.execute(
        "SELECT 1 FROM actor_project_roles apr "
        "JOIN projects pr ON pr.id = apr.project_id "
        f"WHERE apr.actor_id = {p} AND pr.org_id = {p} LIMIT 1",
        (member, org_id),
    ).fetchone()
    if org_role is None and project_role is None:
        return f"requesting actor {member} no longer holds a role in org {org_id}"
    return None


def _require_recorded_end(
    conn: Any, request: Mapping[str, Any], *, org_id: int, state: str
) -> None:
    """Refuse a service delivery the engine's own rows do not show ended.

    Ended means the expiry stored when the request opened has passed by the
    engine's clock, or the requesting member has left the org.
    """
    try:
        require_decision_request_subject_ended(conn, request, observed_at=iso8601_now())
        return
    except ValueError as exc:
        live_evidence = str(exc)
    if _member_departure(conn, int(request["id"]), org_id) is not None:
        return
    raise PermissionError(
        f"hosted_service_withdrawal_subject_live: the hosted service reported "
        f"machine authorization {request.get('subject_key')} {state}, but this "
        f"universe's own records show it has not ended ({live_evidence}; the "
        "requesting member is still active in the org). The hosted service may "
        "end only an authorization whose stored expiry has passed or whose "
        "member has left the org; an org admin withdraws a live one"
    )


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
        _require_recorded_end(conn, request, org_id=org_id, state=state)
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
