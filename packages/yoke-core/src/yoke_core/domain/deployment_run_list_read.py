"""Structured deployment-run presentation read for the universe UI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.deployment_run_carried_work import parse_carried_work
from yoke_core.domain.deployment_run_gates import run_gates
from yoke_core.domain.deployment_runs_schema import _run_named_columns
from yoke_core.domain.actor_project_visibility import actor_visible_project_ids
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES
from yoke_core.domain.workflows_definition_read import _stage_names


OVERVIEW_RUN_WINDOW = timedelta(hours=24)


def append_overview_run_window(
    clauses: list[str],
    params: list[Any],
) -> None:
    """Keep every non-terminal run plus terminals completed in the last 24h."""
    cutoff = (datetime.now(timezone.utc) - OVERVIEW_RUN_WINDOW).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    statuses = tuple(sorted(TERMINAL_RUN_STATUSES))
    markers = ", ".join("%s" for _ in statuses)
    finished = "NULLIF(dr.completed_at, '')"
    clauses.append(f"(dr.status NOT IN ({markers}) OR {finished} >= %s)")
    params.extend([*statuses, cutoff])


RUN_PRESENTATION_FIELDS = (
    "member_items",
    "stages",
    "stage_index",
    "stage_count",
    "gates",
    "overview_priority",
)


def _stage_rows(
    names: list[str],
    *,
    current: str,
    status: str,
) -> tuple[list[dict[str, str]], int]:
    current_index = names.index(current) if current in names else -1
    if names and (status == "succeeded" or current == "complete"):
        current_index = len(names) - 1
    rows: list[dict[str, str]] = []
    for index, name in enumerate(names):
        state = "pending"
        if status == "succeeded" or current == "complete":
            state = "complete"
        elif current_index >= 0 and index < current_index:
            state = "complete"
        elif current_index >= 0 and index == current_index:
            state = {
                "failed": "failed",
                "cancelled": "stopped",
                "executing": "active",
                "created": "active",
            }.get(status, "active")
        rows.append({"name": name, "state": state})
    return rows, current_index


def _member_items(
    conn: Any,
    run_ids: list[str],
    *,
    visible_project_ids: Optional[set[int]] = None,
) -> dict[str, list[dict[str, Any]]]:
    if not run_ids or visible_project_ids == set():
        return {}
    markers = ", ".join("%s" for _ in run_ids)
    visibility = ""
    params: list[Any] = list(run_ids)
    if visible_project_ids is not None:
        project_ids = sorted(visible_project_ids)
        visibility = (
            " AND i.project_id IN (" + ", ".join("%s" for _ in project_ids) + ")"
        )
        params.extend(project_ids)
    rows = conn.execute(
        "SELECT dri.run_id, i.id, i.title, i.status, i.project_sequence, "
        "p.id AS project_id, p.slug AS project, p.public_item_prefix "
        "FROM deployment_run_items dri "
        "JOIN items i ON i.id = dri.item_id "
        "JOIN projects p ON p.id = i.project_id "
        f"WHERE dri.run_id IN ({markers}){visibility} "
        "ORDER BY dri.run_id, i.id",
        tuple(params),
    ).fetchall()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item_id = int(row["id"])
        result.setdefault(str(row["run_id"]), []).append(
            {
                "id": item_id,
                "ref": format_item_ref(
                    str(row["project"]),
                    str(row["public_item_prefix"] or ""),
                    int(row["project_sequence"]),
                ),
                "title": str(row["title"]),
                "status": str(row["status"]),
                "project_id": int(row["project_id"]),
                "project_sequence": int(row["project_sequence"]),
                "project": str(row["project"]),
            }
        )
    return result


def present_deployment_runs(
    conn: Any,
    base: list[dict[str, Any]],
    *,
    actor_id: Optional[int],
    visible_project_ids: Optional[set[int]],
    include_carried_work: bool,
    compact: bool = False,
) -> list[dict[str, Any]]:
    """Add member, stage, and gate facts to already-authorized run rows."""
    run_ids = [str(row["id"]) for row in base]
    members = _member_items(
        conn,
        run_ids,
        visible_project_ids=visible_project_ids,
    )
    gates = run_gates(conn, run_ids, actor_id=actor_id)
    result: list[dict[str, Any]] = []
    for source in base:
        row = dict(source)
        run_id = str(row["id"])
        if include_carried_work:
            carried = parse_carried_work(row.get("carried_work"))
            if compact and carried:
                carried = {
                    "items": [
                        {
                            key: item[key]
                            for key in (
                                "ref",
                                "title",
                                "project_id",
                                "project_sequence",
                                "item_id",
                            )
                            if item.get(key) not in (None, "")
                        }
                        for item in carried.get("items") or []
                        if isinstance(item, dict)
                    ]
                }
            row["carried_work"] = carried
        stage_names = _stage_names(row.pop("stages", None))
        stages, stage_index = _stage_rows(
            stage_names,
            current=str(row.get("current_stage") or ""),
            status=str(row.get("status") or ""),
        )
        run_members = members.get(run_id, [])
        if compact:
            run_members = [
                {
                    key: member[key]
                    for key in ("ref", "title", "project_id", "project_sequence")
                }
                for member in run_members
            ]
        presentation = {
            "member_items": run_members,
            "stages": stages,
            "gates": gates.get(run_id, []),
            "overview_priority": (
                0
                if gates.get(run_id)
                else 2
                if str(row.get("status") or "") in TERMINAL_RUN_STATUSES
                else 1
            ),
        }
        if not compact:
            presentation.update(
                {"stage_index": stage_index, "stage_count": len(stage_names)}
            )
        result.append(
            {
                **{key: ("" if value is None else value) for key, value in row.items()},
                **presentation,
            }
        )
    return result


def list_deployment_runs(
    *,
    project: Optional[str],
    status: Optional[str],
    limit: int,
    actor_id: Optional[int] = None,
    relevance: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return newest runs with member, stage, and gate relationships.

    ``actor_id`` scopes runs and member items to projects this reader may see,
    and decides whether each gate offers the reader its actions. The gate
    itself is reported either way, because a run halted on somebody else is
    still halted.

    ``relevance='overview'`` keeps every non-terminal run plus terminals
    completed in the last 24 hours, applied before ``limit``.
    """
    conn = connect()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        visible_project_ids = actor_visible_project_ids(conn, actor_id)
        if visible_project_ids is not None:
            if not visible_project_ids:
                clauses.append("1 = 0")
            else:
                markers = ", ".join("%s" for _ in visible_project_ids)
                clauses.append(f"dr.project_id IN ({markers})")
                params.extend(sorted(visible_project_ids))
        if project:
            identity = resolve_project(
                conn,
                project,
                required=False,
                visible_project_ids=visible_project_ids,
            )
            if identity is None:
                clauses.append("1 = 0")
            else:
                clauses.append("dr.project_id = %s")
                params.append(identity.id)
        if status:
            clauses.append("dr.status = %s")
            params.append(status)
        if relevance == "overview":
            append_overview_run_window(clauses, params)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        run_columns, env_join = _run_named_columns(conn)
        priority_order = ""
        if relevance == "overview":
            quoted = ", ".join(f"'{status}'" for status in TERMINAL_RUN_STATUSES)
            priority_order = f"CASE WHEN dr.status IN ({quoted}) THEN 1 ELSE 0 END, "
        rows = conn.execute(
            f"SELECT {run_columns}, df.stages "
            "FROM deployment_runs dr "
            "JOIN projects p ON p.id = dr.project_id "
            "JOIN deployment_flows df ON df.id = dr.flow "
            f"{env_join} "
            f"{where}"
            f"ORDER BY {priority_order}dr.created_at DESC, dr.id DESC LIMIT %s",
            (*params, limit),
        ).fetchall()
        base = [dict(row) for row in rows]
        return present_deployment_runs(
            conn,
            base,
            actor_id=actor_id,
            visible_project_ids=visible_project_ids,
            include_carried_work=True,
        )
    finally:
        conn.close()


__all__ = [
    "RUN_PRESENTATION_FIELDS",
    "append_overview_run_window",
    "list_deployment_runs",
    "present_deployment_runs",
]
