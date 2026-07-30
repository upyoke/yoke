"""Internal server-side reads for the resync Stage-1 linkage.

The resync linkage stage opened a local ``connect()`` for its
control-plane reads, which fails over an https control plane (no local
Postgres). These handlers relay those reads server-side (dispatched
in-process against a local Postgres connection, or over https
server-side) while the engine keeps every GitHub REST call local:

* the linkage roster (the project roster drawn from backlog items plus
  active repo bindings, and each project's GitHub sync mode), which the
  engine consumes to drive the per-project GitHub fetch, and
* the backlog + epic-task rows read after the fetch.

Each handler is a thin wrapper over the same queries the engine ran
inline; the sync-mode resolution runs server-side so the engine consumes
plain data. Every orphan/pairing decision stays engine-owned. They are
``adapter_status='internal'`` (engine glue, never an agent CLI surface),
so they carry no CLI adapter row, and read-only, so no authorization
product scope is required. The Stage-2 comparison prefetch lives in the
sibling :mod:`resync_compare_reads` module.
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class LinkageRosterRequest(BaseModel):
    project: str = ""


class LinkageRosterResponse(BaseModel):
    fetch_projects: List[str] = Field(default_factory=list)
    sync_disabled: Dict[str, str] = Field(default_factory=dict)


class LinkageRowsRequest(BaseModel):
    project: str = ""


class LinkageRowsResponse(BaseModel):
    backlog_rows: List[List[Any]] = Field(default_factory=list)
    task_rows: List[List[Any]] = Field(default_factory=list)


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def handle_linkage_roster(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the fetch roster + sync-disabled map for Stage-1 linkage.

    Runs the engine's inline project-roster reads (backlog-derived slugs
    plus active repo bindings) and per-project GitHub sync-mode resolution,
    each with the same ``_table_exists`` guards and operational-error
    rollback fallbacks. Returns the projects to fetch and the sync-disabled
    map the engine folds into its per-project sentinels.
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.projects_github_sync_mode import (
        GITHUB_SYNC_ENABLED,
        resolve_github_sync_mode,
    )
    from yoke_core.domain.schema_common import _table_exists as _schema_table_exists

    try:
        body = LinkageRosterRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err("payload_invalid", f"linkage_roster payload invalid: {exc}")
    project = body.project

    try:
        with _connect_rw() as conn:
            roster: set[str] = {project} if project else {"yoke"}
            if not project:
                try:
                    rows = conn.execute(
                        "SELECT DISTINCT COALESCE(p.slug, 'yoke') "
                        "FROM items i LEFT JOIN projects p ON i.project_id = p.id"
                    ).fetchall()
                    for row in rows:
                        roster.add(row[0])
                except db_backend.operational_error_types(conn):
                    conn.rollback()
                if _schema_table_exists(conn, "project_github_repo_bindings"):
                    try:
                        rows = conn.execute(
                            "SELECT DISTINCT p.slug "
                            "FROM project_github_repo_bindings b "
                            "JOIN projects p ON p.id = b.project_id "
                            "WHERE b.status = 'active'"
                        ).fetchall()
                        for row in rows:
                            roster.add(row[0])
                    except db_backend.operational_error_types(conn):
                        conn.rollback()
            sync_disabled: Dict[str, str] = {}
            for slug in roster:
                mode = resolve_github_sync_mode(slug, conn=conn)
                if mode != GITHUB_SYNC_ENABLED:
                    sync_disabled[slug] = mode
            fetch_projects = sorted(roster.difference(sync_disabled))
    except Exception as exc:  # noqa: BLE001 - surfaced so the engine aborts
        return _err("linkage_roster_failed", str(exc))

    return HandlerOutcome(
        result_payload={
            "fetch_projects": fetch_projects,
            "sync_disabled": sync_disabled,
        },
        primary_success=True,
    )


def _read_backlog_rows(conn: Any, project: str) -> List[List[Any]]:
    from yoke_core.domain import db_backend
    from yoke_core.domain.schema_common import _table_exists as _schema_table_exists

    projects_table_exists = _schema_table_exists(conn, "projects")
    try:
        if projects_table_exists and project:
            rows = conn.execute(
                "SELECT i.id, COALESCE(i.github_issue, ''), p.slug "
                "FROM items i JOIN projects p ON i.project_id = p.id "
                "WHERE p.slug = %s",
                (project,),
            ).fetchall()
        elif projects_table_exists:
            rows = conn.execute(
                "SELECT i.id, COALESCE(i.github_issue, ''), COALESCE(p.slug, 'yoke') "
                "FROM items i LEFT JOIN projects p ON i.project_id = p.id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, COALESCE(github_issue, ''), 'yoke' FROM items"
            ).fetchall()
    except db_backend.operational_error_types(conn):
        conn.rollback()
        rows = (
            conn.execute(
                "SELECT id, COALESCE(github_issue, ''), 'yoke' FROM items"
            ).fetchall()
            if not project or project == "yoke"
            else []
        )
    return [[r[0], r[1], r[2]] for r in rows]


def _read_task_rows(conn: Any, project: str) -> List[List[Any]]:
    from yoke_core.domain import db_backend
    from yoke_core.domain.schema_common import _table_exists as _schema_table_exists

    projects_table_exists = _schema_table_exists(conn, "projects")
    try:
        if projects_table_exists and project:
            rows = conn.execute(
                "SELECT et.epic_id, et.task_num, et.title, et.github_issue, "
                "p.slug FROM epic_tasks et "
                "JOIN items i ON CAST(et.epic_id AS TEXT) = CAST(i.id AS TEXT) "
                "JOIN projects p ON i.project_id = p.id "
                "WHERE p.slug = %s ORDER BY et.epic_id, et.task_num",
                (project,),
            ).fetchall()
        elif projects_table_exists:
            rows = conn.execute(
                "SELECT et.epic_id, et.task_num, et.title, et.github_issue, "
                "COALESCE(p.slug, 'yoke') "
                "FROM epic_tasks et "
                "LEFT JOIN items i ON CAST(et.epic_id AS TEXT) = CAST(i.id AS TEXT) "
                "LEFT JOIN projects p ON i.project_id = p.id "
                "ORDER BY et.epic_id, et.task_num"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT et.epic_id, et.task_num, et.title, et.github_issue, "
                "'yoke' as project "
                "FROM epic_tasks et "
                "ORDER BY et.epic_id, et.task_num"
            ).fetchall()
    except db_backend.operational_error_types(conn):
        conn.rollback()
        return []
    return [[r[0], r[1], r[2], r[3], r[4]] for r in rows]


def handle_linkage_rows(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the Stage-1 backlog + epic-task rows read after the fetch.

    Runs the engine's exact backlog and epic-task reads (all three
    schema-shape variants, with the same operational-error rollback
    fallbacks) and returns the raw positional rows. The engine keeps the
    orphan/pairing classification.
    """
    try:
        body = LinkageRowsRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _err("payload_invalid", f"linkage_rows payload invalid: {exc}")

    try:
        with _connect_rw() as conn:
            backlog_rows = _read_backlog_rows(conn, body.project)
            task_rows = _read_task_rows(conn, body.project)
    except Exception as exc:  # noqa: BLE001 - surfaced so the engine aborts
        return _err("linkage_rows_failed", str(exc))

    return HandlerOutcome(
        result_payload={"backlog_rows": backlog_rows, "task_rows": task_rows},
        primary_success=True,
    )


__all__ = [
    "LinkageRosterRequest",
    "LinkageRosterResponse",
    "LinkageRowsRequest",
    "LinkageRowsResponse",
    "handle_linkage_roster",
    "handle_linkage_rows",
]
