"""Dispose of the Yoke projects one QA plan execution created.

A walk that installs Yoke on its Test Machine creates real control-plane
projects. Walk-end reports the projects that host registers; a reported
project is this execution's fixture only when it was created while the
execution was live (the handler refuses an ended execution) and the walking
actor administers it. Each fixture has its
remaining work claims released, its open items cancelled (which releases
their lanes) and is then retired. Every other reported project is left
untouched and named in the receipt.
"""

from __future__ import annotations

import io
from typing import Any, Iterable

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.db_helpers import query_rows, utc_now

DISPOSAL_REASON = "QA fixture project disposed at walk end"
FIXTURE_PROJECT_DISPOSAL = "fixture_project_disposal"

RETIRED = "retired"
ALREADY_RETIRED = "already_retired"
NOT_CREATED_BY_EXECUTION = "not_created_by_execution"
NOT_FOUND = "not_found"
ADMIN_REQUIRED = "admin_required"
BLOCKED = "blocked"
#: Dispositions no rerun can change; walk-end finishes on them. A project
#: the walker cannot administer stays behind for an administrator, named.
SETTLED = frozenset(
    {RETIRED, ALREADY_RETIRED, NOT_CREATED_BY_EXECUTION, NOT_FOUND, ADMIN_REQUIRED}
)


def _marker(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _project_row(conn: Any, project_id: int) -> dict | None:
    rows = query_rows(
        conn,
        f"SELECT id, slug, created_at, retired_at FROM projects WHERE id={_marker(conn)}",
        (int(project_id),),
    )
    return dict(rows[0]) if rows else None


def _ownership(conn: Any, execution: dict, row: dict | None, actor_id: int) -> str:
    """Return the refusal disposition, or an empty string for an owned fixture."""
    from yoke_core.domain.machine_access_authority import actor_administers_project

    if row is None:
        return NOT_FOUND
    created = parse_instant(row["created_at"])
    if not parse_instant(execution["created_at"]) <= created <= utc_now():
        return NOT_CREATED_BY_EXECUTION
    if not actor_administers_project(conn, actor_id=actor_id, project_id=row["id"]):
        return ADMIN_REQUIRED
    if row["retired_at"] is not None:
        return ALREADY_RETIRED
    return ""


def _release_project_claims(conn: Any, project_id: int) -> list[int]:
    from yoke_core.domain.function_target_row_project import (
        resolve_work_claim_project,
    )
    from yoke_core.domain.sessions_lifecycle_claim_release import release_claim_by_id
    from yoke_core.domain.work_claim_targets import from_row as claim_target

    released = []
    for row in query_rows(
        conn,
        "SELECT id, target_kind, scope FROM work_claims WHERE released_at IS NULL",
    ):
        resolved = resolve_work_claim_project(conn, int(row["id"]))
        if claim_target(row).project_id == project_id or (
            resolved and resolved[0] == project_id
        ):
            release_claim_by_id(conn, int(row["id"]), reason=DISPOSAL_REASON)
            released.append(int(row["id"]))
    conn.commit()
    return released


def _cancel_open_items(
    conn: Any, project_id: int, *, session_id: str
) -> tuple[list[str], list[dict]]:
    from yoke_core.domain.backlog_close_op import execute_close
    from yoke_core.domain.item_terminal_resources import item_is_terminal
    from yoke_core.domain.project_identity import render_item_ref

    cancelled, failures = [], []
    for row in query_rows(
        conn,
        f"SELECT id FROM items WHERE project_id={_marker(conn)} ORDER BY id",
        (project_id,),
    ):
        item_id = int(row["id"])
        if item_is_terminal(conn, item_id) is True:
            continue
        ref = render_item_ref(conn, item_id)
        try:
            result = execute_close(
                item_id, DISPOSAL_REASON, out=io.StringIO(), session_id=session_id
            )
        except Exception as exc:
            conn.rollback()
            result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        if result.get("success"):
            if not result.get("noop"):
                cancelled.append(ref)
        else:
            failures.append({"item": ref, "error": str(result.get("error") or "")})
    conn.commit()
    return cancelled, failures


def dispose_project(
    conn: Any, execution: dict, project_id: int, *, actor_id: int, session_id: str
) -> dict[str, Any]:
    """Dispose of one reported project and return its receipt entry."""
    from yoke_core.domain.project_retirement import (
        ProjectRetirementError,
        set_retirement,
    )

    row = _project_row(conn, project_id)
    entry: dict[str, Any] = {
        "project_id": int(project_id),
        "slug": row["slug"] if row else None,
        "released_claims": [],
        "cancelled_items": [],
        "item_failures": [],
    }
    refused = _ownership(conn, execution, row, actor_id)
    if refused:
        return {**entry, "disposition": refused}
    entry["released_claims"] = _release_project_claims(conn, int(project_id))
    entry["cancelled_items"], entry["item_failures"] = _cancel_open_items(
        conn, int(project_id), session_id=session_id
    )
    try:
        set_retirement(
            conn,
            str(project_id),
            retired=True,
            reason=DISPOSAL_REASON,
            session_id=session_id,
        )
    except ProjectRetirementError as exc:
        conn.rollback()
        return {**entry, "disposition": BLOCKED, "error": f"{exc.code}: {exc}"}
    conn.commit()
    return {**entry, "disposition": RETIRED}


def dispose_projects(
    conn: Any,
    execution: dict,
    project_ids: Iterable[int],
    *,
    actor_id: int,
    session_id: str,
) -> list[dict[str, Any]]:
    """Dispose of each distinct reported project in id order."""
    return [
        dispose_project(
            conn, execution, project_id, actor_id=actor_id, session_id=session_id
        )
        for project_id in sorted({int(p) for p in project_ids})
    ]


def unsettled(receipt: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Receipt entries a rerun of walk-end can still settle."""
    return [entry for entry in receipt if entry["disposition"] not in SETTLED]


def left_for_administrator(receipt: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Settled entries whose project still needs an administrator to retire it."""
    return [entry for entry in receipt if entry["disposition"] == ADMIN_REQUIRED]


__all__ = [
    "DISPOSAL_REASON",
    "FIXTURE_PROJECT_DISPOSAL",
    "dispose_project",
    "dispose_projects",
    "unsettled",
]
