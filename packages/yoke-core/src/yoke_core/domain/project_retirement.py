"""Reversible project retirement and active inventory selection.

Retirement hides inventory entries while retaining every historical row.
Pre-convergence readers preserve the existing inventory until boot adds the
nullable column; writers refuse that window rather than changing schema.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now, query_rows
from yoke_core.domain.item_terminal_resources import item_is_terminal
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.work_claim_targets import from_row as claim_target
from yoke_core.domain.function_target_row_project import resolve_work_claim_project

RETIRED_AT = "retired_at"


class ProjectRetirementError(ValueError):
    """A diagnosed retirement refusal with an actionable recovery."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def active_projects_where(
    conn: Any, *, include_retired: bool = False, alias: str = ""
) -> str:
    """Return the inventory filter, tolerating the self-deploy boot window."""
    if include_retired or not _column_exists(conn, "projects", RETIRED_AT):
        return ""
    return f" WHERE {alias + '.' if alias else ''}{RETIRED_AT} IS NULL"


def project_fields_sql(conn: Any, fields) -> str:
    """Expose retirement state without breaking pre-convergence reads."""
    missing = RETIRED_AT in fields and not _column_exists(conn, "projects", RETIRED_AT)
    return ", ".join(
        "NULL AS retired_at" if field == RETIRED_AT and missing else field
        for field in fields
    )


def retirement_blockers(conn: Any, project_id: int) -> list[str]:
    """Name all active obligations, using each item's pinned terminals."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    items = query_rows(
        conn, f"SELECT id, status FROM items WHERE project_id={marker}", (project_id,)
    )
    blockers = [
        f"open item {row['id']} ({row['status']})"
        for row in items
        if item_is_terminal(conn, int(row["id"])) is not True
    ]
    runs = (
        query_rows(
            conn,
            f"SELECT id, status FROM deployment_runs WHERE project_id={marker} "
            "AND status IN ('created', 'executing')",
            (project_id,),
        )
        if _table_exists(conn, "deployment_runs")
        else []
    )
    blockers.extend(f"deployment run {row['id']} ({row['status']})" for row in runs)
    for row in query_rows(
        conn, "SELECT id, target_kind, scope FROM work_claims WHERE released_at IS NULL"
    ):
        target = claim_target(row)
        resolved = resolve_work_claim_project(conn, int(row["id"]))
        if target.project_id == project_id or (resolved and resolved[0] == project_id):
            blockers.append(f"held {row['target_kind']} claim {row['id']}")
    return blockers


def set_retirement(
    conn: Any, project: str, *, retired: bool, reason: str, session_id: str = ""
) -> dict[str, Any]:
    """Lock, validate, and change the project's visibility without deleting."""
    if not _column_exists(conn, "projects", RETIRED_AT):
        raise ProjectRetirementError(
            "project_retirement_schema_unavailable",
            "Project retirement needs the serving build's boot convergence; "
            "deploy the build carrying projects.retire, then retry.",
        )
    identity = resolve_project(conn, project)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    suffix = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        f"SELECT {RETIRED_AT} FROM projects WHERE id={marker}{suffix}",
        (identity.id,),
    ).fetchone()
    if retired:
        blockers = retirement_blockers(conn, identity.id)
        if blockers:
            raise ProjectRetirementError(
                "project_retirement_blocked",
                f"Cannot retire {identity.slug}: "
                + "; ".join(blockers)
                + ". Complete or cancel open work and runs, and have claim holders "
                "release their holds, then retry.",
            )
    previous = row[RETIRED_AT]
    value = (previous or iso8601_now()) if retired else None
    changed = value != previous
    if changed:
        conn.execute(
            f"UPDATE projects SET {RETIRED_AT}={marker} WHERE id={marker}",
            (value, identity.id),
        )
        from yoke_core.domain.events import emit_event

        emit_event(
            "ProjectRetirementChanged",
            event_kind="lifecycle",
            event_type="project",
            project=identity.slug,
            session_id=session_id,
            conn=conn,
            transactional=True,
            context={"retired_at": value, "reason": reason},
        )
    return {
        "project_id": identity.id,
        "project": identity.slug,
        "retired_at": value,
        "changed": changed,
    }
