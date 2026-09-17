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
from yoke_core.domain.actors import actor_display_labels
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
        "SELECT 1 FROM decision_request_actor_authorities dra "
        "JOIN actors a ON a.id = dra.actor_id AND a.kind = 'human' "
        f"WHERE dra.request_id = {p} AND dra.actor_id = {p}",
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
            f"SELECT 1 FROM {table} ar JOIN actors a ON a.id = ar.actor_id "
            "AND a.kind = 'human' JOIN roles r ON r.id = ar.role_id "
            f"WHERE ar.actor_id = {p} AND ar.{scope_column} = {p} "
            f"AND r.name = {p} LIMIT 1",
            (actor_id, int(row[1]), str(row[2])),
        ).fetchone()
        if match is not None:
            return f"{row[0]} {str(row[2]).replace('_', ' ')}"
    return None


def _role_label(scope_kind: Any, role_name: Any) -> str:
    return f"{scope_kind} {str(role_name).replace('_', ' ')}"


def request_deciders(
    conn: Any,
    request_id: int,
    viewer_actor_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Name everyone who may answer this request now, and how they qualify.

    "Who else can decide" is a question about live membership, so it is
    answered from the same tables the authority predicate reads rather than
    from a list frozen at creation: a person named directly is addressed by
    name, and a role box is answered by whoever holds that role today. A
    surface that showed only the role would tell the reader a policy where
    they asked about people.
    """
    p = _p(conn)
    deciders: dict[int, dict[str, Any]] = {}
    for row in conn.execute(
        "SELECT dra.actor_id FROM decision_request_actor_authorities dra "
        "JOIN actors a ON a.id = dra.actor_id AND a.kind = 'human' "
        f"WHERE dra.request_id = {p} ORDER BY dra.actor_id",
        (request_id,),
    ).fetchall():
        actor_id = int(row[0])
        deciders[actor_id] = {
            "actor_id": actor_id,
            "via": "named",
        }
    roles = conn.execute(
        "SELECT scope_kind, scope_id, role_name "
        "FROM decision_request_role_authorities "
        f"WHERE request_id = {p} ORDER BY role_name, scope_id",
        (request_id,),
    ).fetchall()
    for role in roles:
        table = "actor_org_roles" if role[0] == "org" else "actor_project_roles"
        scope_column = "org_id" if role[0] == "org" else "project_id"
        for holder in conn.execute(
            f"SELECT ar.actor_id FROM {table} ar "
            "JOIN actors a ON a.id = ar.actor_id AND a.kind = 'human' "
            "JOIN roles r ON r.id = ar.role_id "
            f"WHERE ar.{scope_column} = {p} AND r.name = {p} "
            "ORDER BY ar.actor_id",
            (int(role[1]), str(role[2])),
        ).fetchall():
            actor_id = int(holder[0])
            # A person named directly keeps that standing: being asked by
            # name is a stronger fact about why they are here than holding
            # a role that happens to cover the same request.
            if actor_id in deciders:
                continue
            deciders[actor_id] = {
                "actor_id": actor_id,
                "via": _role_label(role[0], role[2]),
            }
    labels = actor_display_labels(conn, deciders)
    for actor_id, decider in deciders.items():
        decider["label"] = labels[actor_id]
    result = sorted(deciders.values(), key=lambda value: value["label"])
    for decider in result:
        decider["is_you"] = (
            viewer_actor_id is not None and decider["actor_id"] == viewer_actor_id
        )
    return result


def decision_request_authority_actor_ids(
    conn: Any,
    request_id: int,
) -> tuple[int, ...]:
    """Resolve live role holders plus frozen named actors for event fan-out."""
    p = _p(conn)
    actor_ids = {
        int(row[0])
        for row in conn.execute(
            "SELECT dra.actor_id FROM decision_request_actor_authorities dra "
            "JOIN actors a ON a.id = dra.actor_id AND a.kind = 'human' "
            f"WHERE dra.request_id = {p}",
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
            "JOIN actors a ON a.id = ar.actor_id AND a.kind = 'human' "
            "JOIN roles r ON r.id = ar.role_id "
            f"WHERE ar.{scope_column} = {p} AND r.name = {p}",
            (int(role[1]), str(role[2])),
        ).fetchall()
        actor_ids.update(int(row[0]) for row in rows)
    return tuple(sorted(actor_ids))


# How many of an actor's own settled requests the Inbox keeps beside what
# still waits on them. The answers themselves are permanent rows in
# ``decision_request_decisions``; this bounds only how far back one reader
# sees their own recent history.
RECENTLY_DECIDED_SHOWN = 10


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
        request["deciders"] = request_deciders(conn, request["id"], actor_id)
        result.append(request)
    result.sort(key=lambda value: (value["decided_by_you"], not value["asked_of_you"]))
    return result


def recently_decided_requests_for_actor(
    conn: Any,
    actor_id: int,
    *,
    project_ids: Optional[Iterable[int]] = None,
    limit: int = RECENTLY_DECIDED_SHOWN,
) -> list[dict[str, Any]]:
    """List the settled requests this actor answered, most recent answer first.

    A request the actor answered stays in ``pending_requests_for_actor`` only
    while the gate itself is still pending. The moment the gate settles the
    request leaves that list, so a reader who had just answered four of them
    reloaded onto an empty history and lost the way back to what they decided.
    Their answers are durable rows, so the settled request is read back through
    the actor's own decision rather than remembered by the page that drew it.

    A settled request offers no actions and cannot be answered again, so it
    carries none: what it still carries is its subject, its evidence, and the
    answer this actor gave it.
    """
    p = _p(conn)
    allowed_projects = (
        {int(value) for value in project_ids} if project_ids is not None else None
    )
    rows = conn.execute(
        "SELECT d.request_id FROM decision_request_decisions d "
        "JOIN decision_requests r ON r.id = d.request_id "
        f"WHERE d.actor_id = {p} AND r.status <> 'pending' "
        "ORDER BY d.decided_at DESC, d.request_id DESC",
        (int(actor_id),),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        if len(result) >= int(limit):
            break
        request = _request_row(conn, int(row[0]))
        if (
            allowed_projects is not None
            and request["project_id"] is not None
            and int(request["project_id"]) not in allowed_projects
        ):
            continue
        reason = authority_reason(conn, request["id"], actor_id)
        request["asked_of_you"] = reason == "asked of you"
        request["authority_reason"] = reason
        request["your_decision"] = actor_decision(conn, request["id"], actor_id)
        request["decided_by_you"] = True
        request["deciders"] = request_deciders(conn, request["id"], actor_id)
        request["actions"] = []
        request["can_act"] = False
        result.append(request)
    return result


def human_role_holders(
    conn: Any,
    *,
    scope_kind: str,
    scope_id: int,
    role_name: str,
) -> tuple[int, ...]:
    """Live human holders of one role; same JOIN ``request_deciders`` uses."""
    table = "actor_org_roles" if scope_kind == "org" else "actor_project_roles"
    scope_column = "org_id" if scope_kind == "org" else "project_id"
    p = _p(conn)
    rows = conn.execute(
        f"SELECT ar.actor_id FROM {table} ar "
        "JOIN actors a ON a.id = ar.actor_id AND a.kind = 'human' "
        "JOIN roles r ON r.id = ar.role_id "
        f"WHERE ar.{scope_column} = {p} AND r.name = {p} "
        "ORDER BY ar.actor_id",
        (int(scope_id), str(role_name)),
    ).fetchall()
    return tuple(int(row[0]) for row in rows)


def unauthorized_resolution_message(
    conn: Any,
    request_id: int,
    actor_id: int,
) -> str:
    """Explain a live authorization miss with recovery, not bare ids."""
    caller = actor_display_labels(conn, (actor_id,)).get(
        int(actor_id), f"actor {actor_id}"
    )
    p = _p(conn)
    roles = list(
        conn.execute(
            "SELECT scope_kind, role_name FROM decision_request_role_authorities "
            f"WHERE request_id = {p} ORDER BY role_name, scope_kind",
            (request_id,),
        ).fetchall()
    )
    named_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM decision_request_actor_authorities "
            f"WHERE request_id = {p}",
            (request_id,),
        ).fetchone()[0]
    )
    required = [_role_label(row[0], row[1]) for row in roles]
    if named_count:
        required.append("a named human")
    required_text = ", ".join(required) or "the request's recorded authority"
    owner_only = [str(row[1]) for row in roles] == ["owner"] and named_count == 0
    deciders = request_deciders(conn, request_id, actor_id)
    humans = (
        "eligible humans: " + ", ".join(str(row["label"]) for row in deciders)
        if deciders
        else "no eligible human currently holds the required authority"
    )
    admin_note = (
        " Org admin does not satisfy this owner-only policy." if owner_only else ""
    )
    return (
        f"{caller} is not authorized for decision request {request_id}: "
        f"required {required_text}. {humans}. Caller is {caller}. "
        "Answer from an eligible human Inbox, or grant a required role to a "
        f"human actor. Do not assign roles automatically.{admin_note}"
    )


__all__ = [
    "RECENTLY_DECIDED_SHOWN",
    "authority_reason",
    "decision_request_authority_actor_ids",
    "human_role_holders",
    "pending_requests_for_actor",
    "recently_decided_requests_for_actor",
    "request_deciders",
    "unauthorized_resolution_message",
]
