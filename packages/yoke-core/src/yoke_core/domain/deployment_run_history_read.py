"""Authorized, compact paging for the dedicated deployment-runs page."""

from __future__ import annotations

import base64
from typing import Any, Collection, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_run_list_read import present_deployment_runs
from yoke_core.domain.json_helper import dumps_compact, loads_text
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES
from yoke_core.domain.schema_common import _column_exists


RUN_HISTORY_FIELDS = (
    "id",
    "project",
    "target_tier",
    "target_environment",
    "status",
    "current_stage",
    "created_at",
    "started_at",
    "completed_at",
    "member_items",
    "stages",
    "gates",
)

_SORT = "COALESCE(NULLIF(dr.created_at, ''), '0001-01-01T00:00:00Z')"


class RunHistoryCursorError(ValueError):
    """A deployment-history cursor is malformed; the message names recovery."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def encode_cursor(sort_value: str, run_id: str) -> str:
    raw = dumps_compact({"created_at": sort_value, "run_id": run_id})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
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
        return created_at, run_id
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


def _scope(
    conn: Any,
    project_ids: Optional[Collection[int]],
) -> tuple[list[str], list[Any]]:
    if project_ids is None:
        return [], []
    ids = sorted({int(value) for value in project_ids})
    if not ids:
        return ["1 = 0"], []
    marker = _p(conn)
    return [f"dr.project_id IN ({', '.join(marker for _ in ids)})"], ids


def _where(clauses: Sequence[str]) -> str:
    return " WHERE " + " AND ".join(clauses) if clauses else ""


def _source(conn: Any) -> tuple[str, str]:
    def column(name: str) -> str:
        return f"dr.{name}" if _column_exists(conn, "deployment_runs", name) else "NULL"

    if _column_exists(conn, "deployment_runs", "target_environment_id"):
        environment = "e.name"
        environment_join = (
            " LEFT JOIN environments e ON e.id = dr.target_environment_id"
        )
    else:
        environment = "NULL"
        environment_join = ""
    fields = ", ".join(
        (
            "dr.id",
            "p.slug AS project",
            f"{column('target_tier')} AS target_tier",
            f"{environment} AS target_environment",
            "dr.status",
            f"{column('current_stage')} AS current_stage",
            "dr.created_at",
            f"{column('started_at')} AS started_at",
            f"{column('completed_at')} AS completed_at",
            "df.stages",
        )
    )
    joins = (
        " FROM deployment_runs dr JOIN projects p ON p.id = dr.project_id "
        "JOIN deployment_flows df ON df.id = dr.flow" + environment_join
    )
    return fields, joins


def _criteria(
    conn: Any,
    *,
    base_clauses: Sequence[str],
    base_params: Sequence[Any],
    project_ids: Optional[Collection[int]],
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
        member_scope = ""
        member_params: list[Any] = []
        if project_ids is not None:
            ids = sorted({int(value) for value in project_ids})
            if not ids:
                member_scope = " AND 1 = 0"
            else:
                member_scope = (
                    " AND i.project_id IN (" + ", ".join(marker for _ in ids) + ")"
                )
                member_params.extend(ids)
        clauses.append(
            "(LOWER(dr.id) LIKE " + marker + " OR EXISTS ("
            "SELECT 1 FROM deployment_run_items dri "
            "JOIN items i ON i.id = dri.item_id "
            "JOIN projects ip ON ip.id = i.project_id "
            "WHERE dri.run_id = dr.id" + member_scope + " AND ("
            "LOWER(i.title) LIKE " + marker + " OR "
            "LOWER(ip.public_item_prefix || '-' || "
            "CAST(i.project_sequence AS TEXT)) LIKE " + marker + ")))"
        )
        params.extend([pattern, *member_params, pattern, pattern])
    return clauses, params


def _filters(
    conn: Any,
    joins: str,
    clauses: Sequence[str],
    params: Sequence[Any],
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
    projects = {int(row["project_id"]): str(row["project"]) for row in rows}
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
) -> dict[str, Any]:
    """Return complete unfinished runs plus one compact completed page."""
    fields, joins = _source(conn)
    scope_clauses, scope_params = _scope(conn, project_ids)
    clauses, params = _criteria(
        conn,
        base_clauses=scope_clauses,
        base_params=scope_params,
        project_ids=project_ids,
        search=search,
        status=status,
        environment=environment,
        flow=flow,
    )
    filters = None if cursor else _filters(conn, joins, clauses, params)
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
            str(last["history_sort_value"]),
            str(last["id"]),
        )
    for row in page:
        row.pop("history_sort_value", None)
    visible = None if project_ids is None else set(project_ids)
    rows = present_deployment_runs(
        conn,
        [*unfinished_rows, *page],
        actor_id=actor_id,
        visible_project_ids=visible,
        include_carried_work=False,
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
