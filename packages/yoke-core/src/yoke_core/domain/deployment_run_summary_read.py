"""Authorized deployment-run summary pages bounded before transport."""

from __future__ import annotations

from typing import Any

from yoke_contracts.timestamps import format_instant
from yoke_core.domain.actor_project_visibility import actor_visible_project_ids
from yoke_core.domain.db_helpers import connect, instant_parameter
from yoke_core.domain.deployment_run_history_read import decode_cursor, encode_cursor
from yoke_core.domain.deployment_run_project_scope import run_project_scope
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.json_helper import dumps_pretty

SUMMARY_FIELDS = (
    "id",
    "project",
    "flow",
    "target_environment",
    "status",
    "current_stage",
    "created_at",
    "release_lineage",
)
# Leave room for the response envelope and CLI indentation within 28,000 bytes.
SUMMARY_PAGE_BYTES = 16_000


def summary_page(rows: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    """Keep whole rows, exposing continuation whenever a bound withheld rows."""
    result: dict[str, Any] = {
        "fields": list(SUMMARY_FIELDS),
        "rows": [],
        "limit": limit,
        "next_cursor": None,
        "detail_recipe": "yoke deployment-runs get RUN-ID FIELD ...",
    }
    for index, row in enumerate(rows[:limit]):
        candidate = {**result, "rows": [*result["rows"], row], "next_cursor": None}
        if index + 1 < len(rows):
            candidate["next_cursor"] = encode_cursor(row["created_at"], row["id"])
        if len(dumps_pretty(candidate).encode("utf-8")) > SUMMARY_PAGE_BYTES:
            if not result["rows"]:
                raise ValueError(
                    "deployment_run_summary_row_too_large: one run exceeds the page budget. "
                    f"Read yoke deployment-runs get {row['id']} status current_stage; "
                    "ask the control-plane operator to shorten oversized run labels."
                )
            break
        result = candidate
    return result


def list_run_summaries(
    *,
    project: str | None,
    status: str | None,
    limit: int,
    cursor: str | None,
    actor_id: int | None,
) -> dict[str, Any]:
    boundary = decode_cursor(cursor) if cursor else None
    conn = connect()
    try:
        visible = actor_visible_project_ids(conn, actor_id)
        clauses, params = run_project_scope(conn, visible)
        if project:
            identity = resolve_project(
                conn, project, required=False, visible_project_ids=visible
            )
            if identity is None:
                clauses.append("1 = 0")
            else:
                scoped, values = run_project_scope(conn, {identity.id})
                clauses.extend(scoped)
                params.extend(values)
        if status:
            clauses.append("dr.status = %s")
            params.append(status)
        if boundary:
            created_at, run_id = boundary
            value = instant_parameter(conn, created_at)
            clauses.append(
                "(dr.created_at < %s OR (dr.created_at = %s AND dr.id < %s))"
            )
            params.extend([value, value, run_id])
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = conn.execute(
            "SELECT dr.id, p.slug AS project, dr.flow, e.name AS target_environment, "
            "dr.status, dr.current_stage, dr.created_at, dr.release_lineage "
            "FROM deployment_runs dr JOIN projects p ON p.id = dr.project_id "
            "LEFT JOIN environments e ON e.id = dr.target_environment_id "
            f"{where} ORDER BY dr.created_at DESC, dr.id DESC LIMIT %s",
            (*params, limit + 1),
        ).fetchall()
        projected = [dict(row) for row in rows]
        for row in projected:
            row["created_at"] = format_instant(row["created_at"])
        return summary_page(projected, limit)
    finally:
        conn.close()
