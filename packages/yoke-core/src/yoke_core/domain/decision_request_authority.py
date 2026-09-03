"""Who may answer a decision request, resolved live rather than snapshotted.

Authority is a predicate over current membership, not a list frozen when the
request was created: a person who holds the addressed role today may answer
today, and a person who lost it may not. That is the same rule the approval
evaluator applies to a role box, read from the same tables, so what the Inbox
offers a person and what their decision satisfies never disagree.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.approval_decisions import actor_decision
from yoke_core.domain.decision_requests import _request_row


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def authority_reason(
    conn: Any,
    request_id: int,
    actor_id: int,
) -> Optional[str]:
    """Return why this actor may answer this request, or ``None`` if they may not."""
    p = _p(conn)
    named = conn.execute(
        "SELECT 1 FROM decision_request_actor_authorities "
        f"WHERE request_id = {p} AND actor_id = {p}",
        (request_id, actor_id),
    ).fetchone()
    if named is not None:
        return "asked of you"
    rows = conn.execute(
        "SELECT scope_kind, scope_id, role_name "
        "FROM decision_request_role_authorities "
        f"WHERE request_id = {p} ORDER BY role_name",
        (request_id,),
    ).fetchall()
    for row in rows:
        table = "actor_org_roles" if row[0] == "org" else "actor_project_roles"
        scope_column = "org_id" if row[0] == "org" else "project_id"
        match = conn.execute(
            f"SELECT 1 FROM {table} ar JOIN roles r ON r.id = ar.role_id "
            f"WHERE ar.actor_id = {p} AND ar.{scope_column} = {p} "
            f"AND r.name = {p} LIMIT 1",
            (actor_id, int(row[1]), str(row[2])),
        ).fetchone()
        if match is not None:
            return f"{row[0]} {str(row[2]).replace('_', ' ')}"
    return None


def decision_request_authority_actor_ids(
    conn: Any,
    request_id: int,
) -> tuple[int, ...]:
    """Resolve live role holders plus frozen named actors for event fan-out."""
    p = _p(conn)
    actor_ids = {
        int(row[0])
        for row in conn.execute(
            "SELECT actor_id FROM decision_request_actor_authorities "
            f"WHERE request_id = {p}",
            (request_id,),
        ).fetchall()
    }
    roles = conn.execute(
        "SELECT scope_kind, scope_id, role_name "
        "FROM decision_request_role_authorities "
        f"WHERE request_id = {p}",
        (request_id,),
    ).fetchall()
    for role in roles:
        table = "actor_org_roles" if role[0] == "org" else "actor_project_roles"
        scope_column = "org_id" if role[0] == "org" else "project_id"
        rows = conn.execute(
            f"SELECT ar.actor_id FROM {table} ar "
            "JOIN roles r ON r.id = ar.role_id "
            f"WHERE ar.{scope_column} = {p} AND r.name = {p}",
            (int(role[1]), str(role[2])),
        ).fetchall()
        actor_ids.update(int(row[0]) for row in rows)
    return tuple(sorted(actor_ids))


def pending_requests_for_actor(
    conn: Any,
    actor_id: int,
    *,
    project_ids: Optional[Iterable[int]] = None,
) -> list[dict[str, Any]]:
    """List what still waits on this actor, and what they have already answered.

    A request the actor already decided stays in their list rather than
    vanishing: under ``all`` it is still open, still theirs to watch, and the
    honest thing to show them is that their own part is done and who the gate
    is now waiting on.
    """
    allowed_projects = (
        {int(value) for value in project_ids} if project_ids is not None else None
    )
    rows = conn.execute(
        "SELECT id FROM decision_requests WHERE status = 'pending' "
        "ORDER BY created_at DESC, id DESC"
    ).fetchall()
    result = []
    for row in rows:
        request = _request_row(conn, int(row[0]))
        if (
            allowed_projects is not None
            and request["project_id"] is not None
            and int(request["project_id"]) not in allowed_projects
        ):
            continue
        reason = authority_reason(conn, request["id"], actor_id)
        if reason is None:
            continue
        decision = actor_decision(conn, request["id"], actor_id)
        request["asked_of_you"] = reason == "asked of you"
        request["authority_reason"] = reason
        request["your_decision"] = decision
        request["decided_by_you"] = decision is not None
        result.append(request)
    result.sort(
        key=lambda value: (value["decided_by_you"], not value["asked_of_you"])
    )
    return result


__all__ = [
    "authority_reason",
    "decision_request_authority_actor_ids",
    "pending_requests_for_actor",
]
