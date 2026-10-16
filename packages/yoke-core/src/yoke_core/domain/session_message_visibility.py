"""Who may read a Fleet message, as one SQL predicate over ``session_messages m``.

Visibility is several separate claims rather than one role check. A sender
always sees what it sent. An addressed actor and an addressed session always
see their own mail, and so does the steering seat currently holding a
role-addressed message -- it was handed that message on acquire and would
otherwise be unable to read the thing it is expected to answer. Everyone
else sees a message only when every session and steering recipient is readable
through its stored project or organization ownership.

List pages filter with this predicate and a single message read checks it
for one id, so both surfaces answer from the same rule.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.actor_message_recipients import ACTOR_KIND
from yoke_core.domain.actor_permissions import PERM_ITEMS_READ, org_permission_decision
from yoke_core.domain.actor_project_visibility import (
    actor_project_ids_with_permission,
)
from yoke_core.domain.steering_message_recipients import STEERING_KIND


def visible_clause(
    conn: Any,
    *,
    actor_id: int,
    caller_session_id: str | None,
) -> tuple[str, list[Any]]:
    """The predicate and parameters that admit messages this caller may read."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    branches = [
        f"m.sender_actor_id={p}",
        "EXISTS (SELECT 1 FROM actor_message_recipients va "
        f"WHERE va.message_id=m.message_id AND va.recipient_kind={p} "
        f"AND va.actor_id={p})",
    ]
    params: list[Any] = [actor_id, ACTOR_KIND, actor_id]
    if caller_session_id:
        branches.extend(
            [
                "EXISTS (SELECT 1 FROM session_message_recipients vs "
                f"WHERE vs.message_id=m.message_id AND vs.session_id={p})",
                "EXISTS (SELECT 1 FROM actor_message_recipients vst "
                f"WHERE vst.message_id=m.message_id AND vst.recipient_kind={p} "
                f"AND vst.seat_session_id={p})",
            ]
        )
        params.extend([caller_session_id, STEERING_KIND, caller_session_id])
    visible_projects = sorted(
        actor_project_ids_with_permission(conn, actor_id, PERM_ITEMS_READ) or []
    )
    orgs = conn.execute(
        f"SELECT DISTINCT org_id FROM actor_org_roles WHERE actor_id={p}", (actor_id,)
    ).fetchall()
    readable_orgs = sorted(
        row[0]
        for row in orgs
        if org_permission_decision(
            conn, actor_id=actor_id, org_id=row[0], permission_key=PERM_ITEMS_READ
        ).allowed
    )
    false = "FALSE" if db_backend.connection_is_postgres(conn) else "1=0"
    slots = ",".join(p for _ in visible_projects)
    project = (
        f"vx.project_id IS NOT NULL AND vx.project_id IN ({slots})" if slots else false
    )
    owner = (
        "EXISTS (SELECT 1 FROM harness_sessions hs "
        f"WHERE hs.session_id=vx.session_id AND hs.actor_id={p})"
    )
    org = owner
    org_params = [actor_id]
    if readable_orgs:
        org += f" OR vx.org_id IN ({','.join(p for _ in readable_orgs)})"
        org_params.extend(readable_orgs)
    steering_hidden = (
        f"vxt.project_id IS NULL OR vxt.project_id NOT IN ({slots})" if slots else "1=1"
    )
    branches.append(
        "("
        "(EXISTS (SELECT 1 FROM session_message_recipients vp "
        "WHERE vp.message_id=m.message_id) OR EXISTS (SELECT 1 FROM "
        "actor_message_recipients vpt WHERE vpt.message_id=m.message_id "
        f"AND vpt.recipient_kind={p})) "
        "AND NOT EXISTS (SELECT 1 FROM session_message_recipients vx "
        "WHERE vx.message_id=m.message_id AND NOT "
        f"(({project}) OR (vx.org_id IS NOT NULL AND ({org})))) "
        "AND NOT EXISTS (SELECT 1 FROM actor_message_recipients vxt "
        f"WHERE vxt.message_id=m.message_id AND vxt.recipient_kind={p} "
        f"AND ({steering_hidden}))"
        ")"
    )
    params.extend(
        [
            STEERING_KIND,
            *visible_projects,
            *org_params,
            STEERING_KIND,
            *visible_projects,
        ]
    )
    return "(" + " OR ".join(branches) + ")", params


def message_visible(
    conn: Any,
    message_id: str,
    *,
    actor_id: int,
    session_id: str | None,
) -> bool:
    """Whether one stored message passes :func:`visible_clause`."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    clause, params = visible_clause(
        conn, actor_id=actor_id, caller_session_id=session_id
    )
    row = conn.execute(
        f"SELECT 1 FROM session_messages m WHERE m.message_id={p} AND {clause}",
        (message_id, *params),
    ).fetchone()
    return row is not None


__all__ = ["message_visible", "visible_clause"]
