"""Resolve a PROJECT-scoped op's project from a persisted target row.

Used when the envelope carries a row id (item, path claim, work claim,
ouroboros entry, QA requirement, deployment run, ephemeral env) but no
explicit ``project`` / ``project_id`` hint. ``--project`` remains an
override via the caller's payload; these helpers only fill the gap when
the named row already knows its project.
"""

from __future__ import annotations

from typing import Any, Collection

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import (
    AmbiguousProjectRefError,
    resolve_project_id,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def slug_for_project_id(conn: Any, project_id: int) -> str:
    p = _p(conn)
    row = conn.execute(
        f"SELECT slug FROM projects WHERE id = {p}",
        (project_id,),
    ).fetchone()
    if row is None:
        return str(project_id)
    return str(row[0])


def resolve_authorized_project_id(
    conn: Any,
    ref: str,
    visible_project_ids: Collection[int] | None,
) -> int:
    if visible_project_ids is None or str(ref).isdigit():
        return resolve_project_id(conn, ref)
    try:
        return resolve_project_id(
            conn,
            ref,
            visible_project_ids=visible_project_ids,
        )
    except AmbiguousProjectRefError:
        raise
    except LookupError:
        return resolve_project_id(conn, ref)


def resolve_item_project(conn: Any, item_id: int) -> tuple[int, str] | None:
    p = _p(conn)
    row = conn.execute(
        "SELECT p.id, p.slug "
        "FROM items i "
        "JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {p}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return None
    return int(row[0]), str(row[1])


def resolve_path_claim_project(
    conn: Any,
    path_claim_id: int,
) -> tuple[int, str] | None:
    """Project authority for a ``path_claims`` row.

    Item-owned claims resolve through the owning item. Session/process
    claims resolve through a covered ``path_targets`` row (all targets on
    one claim share one project).
    """
    p = _p(conn)
    row = conn.execute(
        "SELECT p.id, p.slug "
        "FROM path_claims pc "
        "JOIN items i ON i.id = pc.owner_item_id "
        "JOIN projects p ON p.id = i.project_id "
        f"WHERE pc.id = {p} AND pc.owner_kind = 'item'",
        (int(path_claim_id),),
    ).fetchone()
    if row is not None:
        return int(row[0]), str(row[1])
    row = conn.execute(
        "SELECT p.id, p.slug "
        "FROM path_claim_targets pct "
        "JOIN path_targets pt ON pt.id = pct.target_id "
        "JOIN projects p ON p.id = pt.project_id "
        f"WHERE pct.claim_id = {p} "
        "ORDER BY pct.id LIMIT 1",
        (int(path_claim_id),),
    ).fetchone()
    if row is None:
        return None
    return int(row[0]), str(row[1])


def resolve_ouroboros_entry_project(
    conn: Any,
    entry_id: int,
) -> tuple[int, str] | None:
    """Project authority for an ``ouroboros_entries`` row with ``project_id``."""
    p = _p(conn)
    row = conn.execute(
        "SELECT p.id, p.slug "
        "FROM ouroboros_entries o "
        "JOIN projects p ON p.id = o.project_id "
        f"WHERE o.id = {p}",
        (int(entry_id),),
    ).fetchone()
    if row is None:
        return None
    return int(row[0]), str(row[1])


def resolve_work_claim_project(
    conn: Any,
    claim_id: int,
    *,
    visible_project_ids: Collection[int] | None = None,
) -> tuple[int, str] | None:
    """Resolve project authority from a server-held work-claim row.

    Exact claim release requests intentionally carry only ``work_claims.id``;
    the client must not pre-read tenant state just to manufacture an authz
    hint. Item and epic-task claims resolve through their owning item. Process
    claims encode their registered per-project conflict group as
    ``<group>:<project>``.
    """
    p = _p(conn)
    row = conn.execute(
        "SELECT target_kind, item_id, epic_id, conflict_group "
        f"FROM work_claims WHERE id = {p}",
        (claim_id,),
    ).fetchone()
    if row is None:
        return None
    target_kind = str(row[0])
    if target_kind in {"item", "epic_task"}:
        item_id = row[1] if target_kind == "item" else row[2]
        return resolve_item_project(conn, int(item_id))
    if target_kind != "process":
        return None
    conflict_group = str(row[3] or "")
    _, separator, project_ref = conflict_group.rpartition(":")
    if not separator or not project_ref:
        return None
    try:
        project_id = resolve_authorized_project_id(
            conn,
            project_ref,
            visible_project_ids,
        )
    except (AmbiguousProjectRefError, LookupError):
        return None
    return project_id, slug_for_project_id(conn, project_id)


def resolve_qa_requirement_project(
    conn: Any,
    qa_requirement_id: int,
) -> tuple[int, str] | None:
    p = _p(conn)
    try:
        row = conn.execute(
            "SELECT p.id, p.slug "
            "FROM qa_requirements q "
            "LEFT JOIN items i ON i.id = COALESCE(q.item_id, q.epic_id) "
            "LEFT JOIN deployment_runs dr ON dr.id = q.deployment_run_id "
            "JOIN projects p ON p.id = COALESCE(i.project_id, dr.project_id) "
            f"WHERE q.id = {p}",
            (qa_requirement_id,),
        ).fetchone()
    except db_backend.database_error_types():
        return None
    if row is None:
        return None
    return int(row[0]), str(row[1])


def resolve_deployment_run_project(
    conn: Any,
    deployment_run_id: str,
) -> tuple[int, str] | None:
    p = _p(conn)
    try:
        row = conn.execute(
            "SELECT p.id, p.slug FROM deployment_runs dr "
            "JOIN projects p ON p.id = dr.project_id "
            f"WHERE dr.id = {p}",
            (deployment_run_id,),
        ).fetchone()
    except db_backend.database_error_types():
        return None
    if row is None:
        return None
    return int(row[0]), str(row[1])


def resolve_ephemeral_env_project(
    conn: Any,
    env_id: int,
) -> tuple[int, str] | None:
    p = _p(conn)
    row = conn.execute(
        "SELECT p.id, p.slug "
        "FROM ephemeral_environments ee "
        "JOIN projects p ON p.id = ee.project_id "
        f"WHERE ee.id = {p}",
        (int(env_id),),
    ).fetchone()
    if row is None:
        return None
    return int(row[0]), str(row[1])


__all__ = [
    "resolve_authorized_project_id",
    "resolve_deployment_run_project",
    "resolve_ephemeral_env_project",
    "resolve_item_project",
    "resolve_ouroboros_entry_project",
    "resolve_path_claim_project",
    "resolve_qa_requirement_project",
    "resolve_work_claim_project",
    "slug_for_project_id",
]
