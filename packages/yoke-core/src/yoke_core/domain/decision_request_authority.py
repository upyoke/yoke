"""Who may answer a decision request, resolved live rather than snapshotted.

Authority is a predicate over current membership, not a list frozen when the
request was created: a person who holds the addressed role today may answer
today, and a person who lost it may not. That is the same rule the approval
evaluator applies to a role box, read from the same tables, so what the Inbox
offers a person and what their decision satisfies never disagree.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.actor_render import actor_display_labels
from yoke_core.domain.actor_state import actor_is_active


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _role_boxes(
    conn: Any,
    request_id: int,
    request: Optional[Mapping[str, Any]],
) -> list[tuple[str, int, str]]:
    """This request's role boxes, from the composed row when the caller has
    one and from its own read when it does not."""
    if request is not None:
        return [
            (
                str(authority["scope_kind"]),
                int(authority["scope_id"]),
                str(authority["role_name"]),
            )
            for authority in sorted(
                request.get("role_authorities") or [],
                key=lambda value: str(value["role_name"]),
            )
        ]
    rows = conn.execute(
        "SELECT scope_kind, scope_id, role_name "
        "FROM decision_request_role_authorities "
        f"WHERE request_id = {_p(conn)} ORDER BY role_name",
        (request_id,),
    ).fetchall()
    return [(str(row[0]), int(row[1]), str(row[2])) for row in rows]


def authority_reason(
    conn: Any,
    request_id: int,
    actor_id: int,
    *,
    request: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """Return why this actor may answer this request, or ``None`` if they may not.

    *request* is the already-composed row; passing it keeps a page from
    re-reading the authorities it already holds for every gate it shows.
    """
    p = _p(conn)
    if not actor_is_active(conn, actor_id):
        return None
    named_ids = None if request is None else request.get("named_actor_ids")
    # Being named is only standing if the named actor is a person, so the
    # membership check still runs — but only for an actor the request names.
    if named_ids is None or int(actor_id) in {int(one) for one in named_ids}:
        named = conn.execute(
            "SELECT 1 FROM decision_request_actor_authorities dra "
            "JOIN actors a ON a.id = dra.actor_id AND a.kind = 'human' AND a.status = 'active' "
            f"WHERE dra.request_id = {p} AND dra.actor_id = {p}",
            (request_id, actor_id),
        ).fetchone()
        if named is not None:
            return "asked of you"
    for scope_kind, scope_id, role_name in _role_boxes(conn, request_id, request):
        table = "actor_org_roles" if scope_kind == "org" else "actor_project_roles"
        scope_column = "org_id" if scope_kind == "org" else "project_id"
        match = conn.execute(
            f"SELECT 1 FROM {table} ar JOIN actors a ON a.id = ar.actor_id "
            "AND a.kind = 'human' AND a.status = 'active' JOIN roles r ON r.id = ar.role_id "
            f"WHERE ar.actor_id = {p} AND ar.{scope_column} = {p} "
            f"AND r.name = {p} LIMIT 1",
            (actor_id, scope_id, role_name),
        ).fetchone()
        if match is not None:
            return f"{scope_kind} {role_name.replace('_', ' ')}"
    return None


def _role_label(scope_kind: Any, role_name: Any) -> str:
    return f"{scope_kind} {str(role_name).replace('_', ' ')}"


def request_deciders(
    conn: Any,
    request_id: int,
    viewer_actor_id: Optional[int] = None,
    *,
    request: Optional[Mapping[str, Any]] = None,
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
        "JOIN actors a ON a.id = dra.actor_id AND a.kind = 'human' AND a.status = 'active' "
        f"WHERE dra.request_id = {p} ORDER BY dra.actor_id",
        (request_id,),
    ).fetchall():
        actor_id = int(row[0])
        deciders[actor_id] = {
            "actor_id": actor_id,
            "via": "named",
        }
    if request is not None:
        roles = [
            (
                str(authority["scope_kind"]),
                int(authority["scope_id"]),
                str(authority["role_name"]),
            )
            for authority in sorted(
                request.get("role_authorities") or [],
                key=lambda value: (str(value["role_name"]), int(value["scope_id"])),
            )
        ]
    else:
        roles = [
            (str(row[0]), int(row[1]), str(row[2]))
            for row in conn.execute(
                "SELECT scope_kind, scope_id, role_name "
                "FROM decision_request_role_authorities "
                f"WHERE request_id = {p} ORDER BY role_name, scope_id",
                (request_id,),
            ).fetchall()
        ]
    for scope_kind, scope_id, role_name in roles:
        table = "actor_org_roles" if scope_kind == "org" else "actor_project_roles"
        scope_column = "org_id" if scope_kind == "org" else "project_id"
        for holder in conn.execute(
            f"SELECT ar.actor_id FROM {table} ar "
            "JOIN actors a ON a.id = ar.actor_id AND a.kind = 'human' AND a.status = 'active' "
            "JOIN roles r ON r.id = ar.role_id "
            f"WHERE ar.{scope_column} = {p} AND r.name = {p} "
            "ORDER BY ar.actor_id",
            (scope_id, role_name),
        ).fetchall():
            actor_id = int(holder[0])
            # A person named directly keeps that standing: being asked by
            # name is a stronger fact about why they are here than holding
            # a role that happens to cover the same request.
            if actor_id in deciders:
                continue
            deciders[actor_id] = {
                "actor_id": actor_id,
                "via": _role_label(scope_kind, role_name),
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
            "JOIN actors a ON a.id = dra.actor_id AND a.kind = 'human' AND a.status = 'active' "
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
            "JOIN actors a ON a.id = ar.actor_id AND a.kind = 'human' AND a.status = 'active' "
            "JOIN roles r ON r.id = ar.role_id "
            f"WHERE ar.{scope_column} = {p} AND r.name = {p}",
            (int(role[1]), str(role[2])),
        ).fetchall()
        actor_ids.update(int(row[0]) for row in rows)
    return tuple(sorted(actor_ids))


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
        "JOIN actors a ON a.id = ar.actor_id AND a.kind = 'human' AND a.status = 'active' "
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
    "authority_reason",
    "decision_request_authority_actor_ids",
    "human_role_holders",
    "request_deciders",
    "unauthorized_resolution_message",
]
