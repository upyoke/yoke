"""Structured deployment-run presentation read for the universe UI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.deployment_run_member_presentation import (
    _member_items,
    removed_member_items,
)
from yoke_core.domain.deployment_run_bound_sources import parse_bound_sources
from yoke_core.domain.deployment_run_carried_work_read import (
    compact_carried_work,
    read_carried_work,
)
from yoke_core.domain.deployment_run_contained_items import (
    parse_candidate_containment,
)
from yoke_core.domain.deployment_run_item_delivery import candidate_delivery_items
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
    "removed_member_items",
    "contained_items",
    "delivery_candidate_items",
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


def present_deployment_runs(
    conn: Any,
    base: list[dict[str, Any]],
    *,
    actor_id: Optional[int],
    visible_project_ids: Optional[set[int]],
    include_carried_work: bool,
    compact: bool = False,
    include_item_delivery: bool = False,
) -> list[dict[str, Any]]:
    """Add member, stage, and gate facts to already-authorized run rows."""
    run_ids = [str(row["id"]) for row in base]
    members = _member_items(
        conn,
        run_ids,
        visible_project_ids=visible_project_ids,
    )
    removed = removed_member_items(conn, base, visible_project_ids=visible_project_ids)
    for run_id, entries in removed.items():
        excluded = {entry["id"] for entry in entries}
        members[run_id] = [
            m for m in members.get(run_id, []) if m["id"] not in excluded
        ]
    from yoke_core.domain.deployment_qa_run_acceptance import member_qa_standings

    qa = (
        member_qa_standings(
            conn,
            [
                (str(row["id"]), int(member["id"]), str(row.get("current_stage") or ""))
                for row in base
                for member in members.get(str(row["id"]), [])
            ],
        )
        if include_item_delivery
        else {}
    )
    if include_item_delivery:
        for run_id, run_members in members.items():
            for member in run_members:
                member["item_qa"] = qa.get((run_id, int(member["id"])))
    gates = run_gates(conn, run_ids, actor_id=actor_id)
    delivery_items = (
        candidate_delivery_items(conn, base) if include_item_delivery else {}
    )
    result: list[dict[str, Any]] = []
    for source in base:
        row = dict(source)
        run_id = str(row["id"])
        row.pop("membership_removals", None)
        if include_carried_work:
            carried = read_carried_work(conn, row)
            row["carried_work"] = compact_carried_work(carried) if compact else carried
        if "bound_sources" in row:
            # Pinned sources are the same record delivery is judged on.
            row["bound_sources"] = parse_bound_sources(row.get("bound_sources"))
        recorded_containment = row.pop("candidate_containment", None)
        containment = parse_candidate_containment(recorded_containment)
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
                    for key in (
                        "id",
                        "ref",
                        "title",
                        "status",
                        "project_id",
                        "project_sequence",
                        "item_qa",
                    )
                    if key in member
                }
                for member in run_members
            ]
        # Candidate containment joins memberless in-flight runs to cards.
        contained: list[dict[str, Any]] = []
        if (
            str(row.get("status") or "") not in TERMINAL_RUN_STATUSES
            and not run_members
        ):
            contained = [
                item
                for item in containment.get("items") or []
                if visible_project_ids is None
                or int(item.get("project_id") or 0) in visible_project_ids
            ]
        presentation = {
            "member_items": run_members,
            "removed_member_items": removed.get(run_id, []),
            "contained_items": contained,
            "stages": stages,
            "gates": gates.get(run_id, []),
            "overview_priority": (
                0
                if any(
                    gate.get("status") == "pending" for gate in gates.get(run_id, [])
                )
                else 2
                if str(row.get("status") or "") in TERMINAL_RUN_STATUSES
                else 1
            ),
        }
        if include_item_delivery and recorded_containment and "answers" in containment:
            presentation["delivery_candidate_items"] = [
                item
                for item in delivery_items.get(run_id, [])
                if visible_project_ids is None
                or int(item["project_id"]) in visible_project_ids
            ]
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
    """Return authorized runs with member QA, stages, and gates.

    Overview keeps live runs and the last 24 hours of completions before limit.
    """
    conn = connect()
    try:
        clauses: list[str] = []
        params: list[Any] = []
        visible_project_ids = actor_visible_project_ids(conn, actor_id)
        from yoke_core.domain.deployment_run_project_scope import run_project_scope

        visible_clauses, visible_params = run_project_scope(conn, visible_project_ids)
        clauses.extend(visible_clauses)
        params.extend(visible_params)
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
                project_clauses, project_params = run_project_scope(conn, {identity.id})
                clauses.extend(project_clauses)
                params.extend(project_params)
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
            visible_project_ids=None,
            include_carried_work=True,
            include_item_delivery=relevance == "overview",
        )
    finally:
        conn.close()


__all__ = [
    "RUN_PRESENTATION_FIELDS",
    "append_overview_run_window",
    "list_deployment_runs",
    "present_deployment_runs",
]
