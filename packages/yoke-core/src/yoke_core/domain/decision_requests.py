"""Decision-request lifecycle, live authority union, and Inbox reads."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable, Mapping, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.decision_request_contract import (
    DECISION_KINDS,
    LIFECYCLE_TRANSITION_APPROVAL,
    REQUEST_CREATED_EVENT,
)
from yoke_core.domain.decision_request_events import append_decision_event
from yoke_core.domain.decision_request_subject_context import validate_subject_context
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
    rollback_workflow_binding_write_errors,
)


@dataclass(frozen=True)
class RoleAuthority:
    scope_kind: str
    scope_id: int
    role_name: str


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _request_row(conn: Any, request_id: int) -> dict[str, Any]:
    p = _p(conn)
    row = conn.execute(
        f"SELECT * FROM decision_requests WHERE id = {p}",
        (request_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"decision request {request_id} does not exist")
    result = dict(row)
    try:
        result["subject_context"] = json.loads(result["subject_context"] or "{}")
    except (TypeError, json.JSONDecodeError):
        result["subject_context"] = {}
    result["actions"] = list(DECISION_KINDS[result["kind"]].actions)
    result["role_authorities"] = [
        dict(value)
        for value in conn.execute(
            "SELECT scope_kind, scope_id, role_name "
            "FROM decision_request_role_authorities "
            f"WHERE request_id = {p} ORDER BY role_name, scope_id",
            (request_id,),
        ).fetchall()
    ]
    result["named_actor_ids"] = [
        int(value[0])
        for value in conn.execute(
            "SELECT actor_id FROM decision_request_actor_authorities "
            f"WHERE request_id = {p} ORDER BY actor_id",
            (request_id,),
        ).fetchall()
    ]
    return result


def _validate_scope(
    conn: Any,
    *,
    kind: str,
    project_id: Optional[int],
    org_id: Optional[int],
    role_authorities: tuple[RoleAuthority, ...],
) -> None:
    spec = DECISION_KINDS[kind]
    if spec.role_scope == "project" and (project_id is None or org_id is not None):
        raise ValueError(f"{kind} requires exactly one project scope")
    if spec.role_scope == "org" and (org_id is None or project_id is not None):
        raise ValueError(f"{kind} requires exactly one organization scope")
    p = _p(conn)
    project_org_id = None
    if project_id is not None:
        project = conn.execute(
            f"SELECT org_id FROM projects WHERE id = {p}",
            (project_id,),
        ).fetchone()
        if project is None:
            raise LookupError(f"project {project_id} does not exist")
        project_org_id = int(project[0]) if project[0] is not None else None
    for authority in role_authorities:
        if authority.role_name not in spec.allowed_roles:
            raise ValueError(
                f"role {authority.role_name!r} is outside {kind}'s role vocabulary"
            )
        expected_scope = "org" if authority.role_name == "admin" else "project"
        if authority.scope_kind != expected_scope:
            raise ValueError(
                f"role {authority.role_name!r} requires {expected_scope} scope"
            )
        expected_id = org_id if expected_scope == "org" else project_id
        if project_id is not None and expected_scope == "org":
            expected_id = project_org_id
        if expected_id is None or authority.scope_id != expected_id:
            raise ValueError(
                f"{authority.role_name!r} authority does not match the subject scope"
            )


@rollback_workflow_binding_write_errors
def create_decision_request(
    conn: Any,
    *,
    kind: str,
    subject_type: str,
    subject_key: str,
    project_id: Optional[int] = None,
    org_id: Optional[int] = None,
    originator_actor_id: Optional[int] = None,
    role_authorities: Iterable[RoleAuthority] = (),
    named_actor_ids: Iterable[int] = (),
    subject_context: Optional[Mapping[str, Any]] = None,
    session_id: str = "",
    created_at: Optional[str] = None,
    commit: bool = True,
) -> tuple[dict[str, Any], bool]:
    """Create once per open typed subject; repeated gate attempts reuse it."""
    if kind not in DECISION_KINDS:
        raise ValueError(f"unknown decision request kind {kind!r}")
    spec = DECISION_KINDS[kind]
    if subject_type != spec.subject_type:
        raise ValueError(f"{kind} requires subject_type={spec.subject_type!r}")
    subject_key = str(subject_key).strip()
    if not subject_key or len(subject_key) > 500:
        raise ValueError("subject_key must contain 1 to 500 characters")
    roles = tuple(role_authorities)
    actors = tuple(sorted({int(value) for value in named_actor_ids}))
    if not roles and not actors:
        raise ValueError("at least one role or named actor authority is required")
    _validate_scope(
        conn,
        kind=kind,
        project_id=project_id,
        org_id=org_id,
        role_authorities=roles,
    )
    if kind == LIFECYCLE_TRANSITION_APPROVAL and subject_type == "item_transition":
        parts = subject_key.split(":")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].strip():
            raise ValueError(
                "lifecycle approval subject_key must be '<item_id>:<stage_id>'"
            )
        lock_item_workflow_bindings(conn, (int(parts[0]),))
    p = _p(conn)
    stamp = created_at or iso8601_now()
    cursor = conn.execute(
        "INSERT INTO decision_requests "
        "(kind, subject_type, subject_key, subject_context, project_id, org_id, "
        "originator_actor_id, status, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, 'pending', {p}) "
        "ON CONFLICT DO NOTHING RETURNING id",
        (
            kind,
            subject_type,
            subject_key,
            json.dumps(validate_subject_context(kind, subject_context), separators=(",", ":")),
            project_id,
            org_id,
            originator_actor_id,
            stamp,
        ),
    )
    inserted = cursor.fetchone()
    created = inserted is not None
    if created:
        request_id = int(inserted[0])
        for authority in roles:
            conn.execute(
                "INSERT INTO decision_request_role_authorities "
                "(request_id, scope_kind, scope_id, role_name) "
                f"VALUES ({p}, {p}, {p}, {p})",
                (
                    request_id,
                    authority.scope_kind,
                    authority.scope_id,
                    authority.role_name,
                ),
            )
        for actor_id in actors:
            conn.execute(
                "INSERT INTO decision_request_actor_authorities "
                f"(request_id, actor_id) VALUES ({p}, {p})",
                (request_id, actor_id),
            )
        append_decision_event(
            conn,
            REQUEST_CREATED_EVENT,
            actor_id=originator_actor_id,
            session_id=session_id,
            project_id=project_id,
            org_id=org_id,
            context={
                "request_id": request_id,
                "kind": kind,
                "subject_type": subject_type,
                "subject_key": subject_key,
            },
            created_at=stamp,
        )
        if commit:
            conn.commit()
    else:
        row = conn.execute(
            "SELECT id FROM decision_requests "
            f"WHERE kind = {p} AND subject_type = {p} AND subject_key = {p} "
            "AND status = 'pending'",
            (kind, subject_type, subject_key),
        ).fetchone()
        if row is None:
            raise RuntimeError("decision request idempotency race did not converge")
        request_id = int(row[0])
        if commit:
            conn.commit()
    return _request_row(conn, request_id), created


def _authority_reason(
    conn: Any,
    request_id: int,
    actor_id: int,
) -> Optional[str]:
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


def list_subject_requests(
    conn: Any,
    subject_type: str,
    subject_key: str,
) -> list[dict[str, Any]]:
    """Return the immutable lifecycle history for one typed subject."""
    p = _p(conn)
    rows = conn.execute(
        "SELECT id FROM decision_requests "
        f"WHERE subject_type = {p} AND subject_key = {p} "
        "ORDER BY created_at DESC, id DESC",
        (subject_type, subject_key),
    ).fetchall()
    return [_request_row(conn, int(row[0])) for row in rows]


def pending_requests_for_actor(
    conn: Any,
    actor_id: int,
    *,
    project_ids: Optional[Iterable[int]] = None,
) -> list[dict[str, Any]]:
    """Evaluate live role predicates and frozen names for one actor."""
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
        reason = _authority_reason(conn, request["id"], actor_id)
        if reason is None:
            continue
        request["asked_of_you"] = reason == "asked of you"
        request["authority_reason"] = reason
        result.append(request)
    result.sort(key=lambda value: not value["asked_of_you"])
    return result


__all__ = [
    "RoleAuthority",
    "create_decision_request",
    "decision_request_authority_actor_ids",
    "list_subject_requests",
    "pending_requests_for_actor",
]
