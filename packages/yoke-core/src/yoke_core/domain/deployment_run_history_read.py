"""Authorized, compact paging for the dedicated deployment-runs page."""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Any, Collection, Optional, Sequence

from yoke_contracts.timestamps import format_instant, parse_instant
from yoke_core.domain import db_backend
from yoke_core.domain.deployment_run_project_scope import run_project_scope
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.deployment_run_list_read import present_deployment_runs
from yoke_core.domain.deployment_runs_schema import history_run_columns
from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES
from yoke_core.domain.schema_common import _column_exists


RUN_HISTORY_FIELDS = (
    "id",
    "project",
    "flow",
    "flow_name",
    "target_tier",
    "target_environment",
    "status",
    "current_stage",
    "created_at",
    "started_at",
    "completed_at",
    "carried_work",
    "bound_sources",
    "release_lineage",
    "artifact_identity",
    "composition_frozen_at",
    "member_items",
    "removed_member_items",
    "stages",
    "gates",
)

_SORT = "dr.created_at"


class RunHistoryCursorError(ValueError):
    """A deployment-history cursor is malformed; the message names recovery."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def encode_cursor(sort_value: datetime | str, run_id: str) -> str:
    raw = dumps_compact({"created_at": format_instant(sort_value), "run_id": run_id})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = loads_text(
            base64.urlsafe_b64decode(
                (cursor + padding).encode(),
            ).decode()
        )
        created_at = payload["created_at"]
        run_id = payload["run_id"]
        if set(payload) != {"created_at", "run_id"}:
            raise ValueError
        if not isinstance(created_at, str) or not created_at:
            raise ValueError
        if not isinstance(run_id, str) or not run_id:
            raise ValueError
        return parse_instant(created_at), run_id
    except (KeyError, TypeError, UnicodeError, ValueError):
        raise RunHistoryCursorError(
            "Runs page cursor is malformed. Reload the first Runs page "
            "without a cursor."
        ) from None


def _dict_rows(cursor: Any) -> list[dict[str, Any]]:
    rows = cursor.fetchall()
    if not rows:
        return []
    if hasattr(rows[0], "keys"):
        return [dict(row) for row in rows]
    columns = [str(column[0]) for column in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


def _where(clauses: Sequence[str]) -> str:
    return " WHERE " + " AND ".join(clauses) if clauses else ""


def _criteria(
    conn: Any,
    *,
    base_clauses: Sequence[str],
    base_params: Sequence[Any],
    visible_project_ids: Optional[set[int]],
    search: Optional[str],
    status: Optional[str],
    environment: Optional[str],
    flow: Optional[str],
) -> tuple[list[str], list[Any]]:
    marker = _p(conn)
    clauses = list(base_clauses)
    params = list(base_params)
    if status:
        clauses.append(f"dr.status = {marker}")
        params.append(status)
    if flow:
        clauses.append(f"dr.flow = {marker}")
        params.append(flow)
    if environment:
        if _column_exists(conn, "deployment_runs", "target_environment_id"):
            clauses.append(f"e.name = {marker}")
            params.append(environment)
        else:
            clauses.append("1 = 0")
    normalized_search = str(search or "").strip().lower()
    if normalized_search:
        pattern = f"%{normalized_search}%"
        scope = ""
        visible = sorted(visible_project_ids or ())
        if visible_project_ids is not None:
            scope = (
                f" AND i.project_id IN ({','.join([marker] * len(visible))})"
                if visible
                else " AND 1=0"
            )
        clauses.append(
            "(LOWER(dr.id) LIKE " + marker + " OR EXISTS ("
            "SELECT 1 FROM deployment_run_items dri "
            "JOIN items i ON i.id = dri.item_id "
            "JOIN item_refs ir ON ir.item_id = i.id "
            f"WHERE dri.run_id = dr.id{scope} AND ("
            "LOWER(i.title) LIKE " + marker + " OR "
            "LOWER(ir.public_ref) LIKE " + marker + ")))"
        )
        params.extend([pattern, *visible, pattern, pattern])
    return clauses, params


def _filters(
    conn: Any,
    joins: str,
    clauses: Sequence[str],
    params: Sequence[Any],
    visible_project_ids: Optional[set[int]],
) -> dict[str, Any]:
    rows = _dict_rows(
        conn.execute(
            "SELECT DISTINCT dr.project_id, p.slug AS project, dr.status, "
            "dr.flow, df.name AS flow_name, "
            + ("e.name" if " environments e " in joins else "NULL")
            + " AS target_environment"
            + joins
            + _where(clauses),
            tuple(params),
        )
    )
    projects = {
        int(row["project_id"]): str(row["project"])
        for row in rows
        if visible_project_ids is None or int(row["project_id"]) in visible_project_ids
    }
    flows = {
        str(row["flow"]): str(row.get("flow_name") or row["flow"])
        for row in rows
        if row.get("flow")
    }
    return {
        "projects": [
            {"id": project_id, "label": projects[project_id]}
            for project_id in sorted(projects, key=lambda key: projects[key].lower())
        ],
        "statuses": sorted({str(row["status"]) for row in rows if row.get("status")}),
        "environments": sorted(
            {
                str(row["target_environment"])
                for row in rows
                if row.get("target_environment")
            }
        ),
        "flows": [
            {"id": flow_id, "label": flows[flow_id]}
            for flow_id in sorted(flows, key=lambda key: flows[key].lower())
        ],
    }


def read_deployment_run_history(
    conn: Any,
    *,
    project_ids: Optional[Collection[int]],
    search: Optional[str],
    status: Optional[str],
    environment: Optional[str],
    flow: Optional[str],
    page_size: int,
    cursor: Optional[str],
    actor_id: Optional[int],
    visible_project_ids: Optional[set[int]],
) -> dict[str, Any]:
    """Return complete unfinished runs plus one compact completed page."""
    if visible_project_ids is not None:
        project_ids = (
            visible_project_ids
            if project_ids is None
            else visible_project_ids.intersection(project_ids)
        )
    fields, joins = history_run_columns(conn)
    scope_clauses, scope_params = run_project_scope(conn, project_ids)
    clauses, params = _criteria(
        conn,
        base_clauses=scope_clauses,
        base_params=scope_params,
        visible_project_ids=visible_project_ids,
        search=search,
        status=status,
        environment=environment,
        flow=flow,
    )
    filters = (
        None if cursor else _filters(conn, joins, clauses, params, visible_project_ids)
    )
    marker = _p(conn)
    terminals = sorted(TERMINAL_RUN_STATUSES)
    terminal_markers = ", ".join(marker for _ in terminals)
    unfinished_clauses = [*clauses, f"dr.status NOT IN ({terminal_markers})"]
    completed_clauses = [*clauses, f"dr.status IN ({terminal_markers})"]
    partition_params = [*params, *terminals]
    unfinished_rows = _dict_rows(
        conn.execute(
            f"SELECT {fields}{joins}{_where(unfinished_clauses)} "
            f"ORDER BY {_SORT} DESC, dr.id DESC",
            tuple(partition_params),
        )
    )
    unfinished_count = int(
        conn.execute(
            "SELECT COUNT(*)" + joins + _where(unfinished_clauses),
            tuple(partition_params),
        ).fetchone()[0]
    )
    completed_count = int(
        conn.execute(
            "SELECT COUNT(*)" + joins + _where(completed_clauses),
            tuple(partition_params),
        ).fetchone()[0]
    )

    completed_params = list(partition_params)
    loaded_before = 0
    if cursor:
        sort_value, run_id = decode_cursor(cursor)
        sort_value = instant_parameter(conn, sort_value)
        ahead = [
            *completed_clauses,
            f"({_SORT} > {marker} OR ({_SORT} = {marker} AND dr.id >= {marker}))",
        ]
        loaded_before = int(
            conn.execute(
                "SELECT COUNT(*)" + joins + _where(ahead),
                (*partition_params, sort_value, sort_value, run_id),
            ).fetchone()[0]
        )
        completed_clauses.append(
            f"({_SORT} < {marker} OR ({_SORT} = {marker} AND dr.id < {marker}))"
        )
        completed_params.extend([sort_value, sort_value, run_id])
    completed_rows = _dict_rows(
        conn.execute(
            f"SELECT {fields}, {_SORT} AS history_sort_value"
            f"{joins}{_where(completed_clauses)} "
            f"ORDER BY {_SORT} DESC, dr.id DESC LIMIT {marker}",
            (*completed_params, page_size + 1),
        )
    )
    has_more = len(completed_rows) > page_size
    page = completed_rows[:page_size]
    loaded = loaded_before + len(page)
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor(
            last["history_sort_value"],
            str(last["id"]),
        )
    for row in page:
        row.pop("history_sort_value", None)
    rows = present_deployment_runs(
        conn,
        [*unfinished_rows, *page],
        actor_id=actor_id,
        visible_project_ids=visible_project_ids,
        include_carried_work=True,
        compact=True,
    )
    return {
        "fields": list(RUN_HISTORY_FIELDS),
        "rows": rows,
        "limit": page_size,
        "unfinished_count": unfinished_count,
        "completed_match_count": completed_count,
        "completed_loaded_count": loaded,
        "next_cursor": next_cursor,
        "filters": filters,
    }
