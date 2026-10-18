"""Bounded live-run status reads for one steering report request.

Facts are retrieved once for the live set; scoped QA uses qa_stage_outstanding.
"""

from __future__ import annotations

from yoke_core.domain.steering_fleet_report_detectors import parse_stamp

from datetime import datetime

from dataclasses import dataclass
from typing import Any

from yoke_core.domain.deployment_run_stage_entry import (
    is_scoped_qa_stage,
    parse_stage_plan,
)
from yoke_core.domain.deployment_run_red_requirements import (
    RedRequirement,
    red_blocking_requirements,
)
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.qa_review_waits import requirements_awaiting_human_review
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_message_types import row_dict
from yoke_core.domain.steering_fleet_report_detectors import marker


_FACT_TABLES = (
    "deployment_runs",
    "deployment_flows",
    "qa_requirements",
    "qa_runs",
    "decision_requests",
    "deployment_run_items",
)


@dataclass(frozen=True)
class LiveRunFactMaps:
    """One report request's live-run status facts, keyed by run id."""

    #: Runs standing on a scoped-QA stage, with that stage's name.
    qa_stages: dict[str, str]
    #: Each scoped-QA run's member item ids, in id order.
    members: dict[str, tuple[int, ...]]
    entered_at: dict[str, datetime]
    red: dict[str, tuple[RedRequirement, ...]]
    decisions: dict[str, dict[str, Any]]
    unresolved: dict[str, tuple[str, ...]]
    totals: dict[str, int]


@dataclass
class _Tables:
    names: frozenset[str]

    def has(self, name: str) -> bool:
        return name in self.names


def probe_report_tables(conn: Any) -> _Tables:
    """Presence of every table this report request will read, asked once."""
    return _Tables(
        frozenset(name for name in _FACT_TABLES if _table_exists(conn, name))
    )


def live_deployment_runs(conn: Any, *, project_id: int) -> list[dict[str, Any]]:
    p = marker(conn)
    terminal = sorted(TERMINAL_RUN_STATUSES)
    holes = ", ".join(p for _ in terminal)
    rows = conn.execute(
        f"""SELECT id, flow, status, COALESCE(current_stage, '') AS current_stage,
                   current_stage_entered_at, driver_attachment,
                   settling_at
              FROM deployment_runs
             WHERE project_id = {p}
               AND status NOT IN ({holes})
             ORDER BY id""",
        (int(project_id), *terminal),
    ).fetchall()
    return [row_dict(row) for row in rows]


def load_live_run_facts(
    conn: Any,
    *,
    runs: list[dict[str, Any]],
    tables: _Tables,
) -> LiveRunFactMaps:
    """Stage clocks, red verdicts, decisions, and completion-boundary counts."""
    run_ids = [str(run["id"]) for run in runs]
    if not run_ids:
        return LiveRunFactMaps({}, {}, {}, {}, {}, {}, {})
    plans = _flow_stage_plans(conn, runs=runs, tables=tables)
    qa_stages = _qa_stages(runs=runs, plans=plans)
    unresolved, totals = _completion_boundary(
        conn,
        run_ids=[run_id for run_id in run_ids if run_id not in qa_stages],
        tables=tables,
    )
    return LiveRunFactMaps(
        qa_stages=qa_stages,
        members=_qa_stage_members(conn, run_ids=list(qa_stages), tables=tables),
        entered_at={
            str(run["id"]): parse_stamp(run["current_stage_entered_at"])
            for run in runs
            if run.get("current_stage_entered_at")
        },
        red=red_blocking_requirements(conn, run_ids),
        decisions=_resolved_decisions(conn, runs=runs, tables=tables),
        unresolved=unresolved,
        totals=totals,
    )


def _holes(conn: Any, values: list[Any]) -> tuple[str, tuple[Any, ...]]:
    p = marker(conn)
    return ", ".join(p for _ in values), tuple(values)


def _flow_stage_plans(
    conn: Any, *, runs: list[dict[str, Any]], tables: _Tables
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Each live run's pinned flow stages, in order, read once."""
    if not tables.has("deployment_flows"):
        return {}
    run_ids = [str(run["id"]) for run in runs]
    holes, params = _holes(conn, run_ids)
    rows = conn.execute(
        f"""SELECT dr.id, df.stages
              FROM deployment_runs dr
              JOIN deployment_flows df ON df.id = dr.flow
             WHERE dr.id IN ({holes})""",
        params,
    ).fetchall()
    plans: dict[str, tuple[dict[str, Any], ...]] = {}
    for raw in rows:
        row = row_dict(raw)
        plans[str(row["id"])] = parse_stage_plan(row.get("stages"))
    return plans


def _qa_stages(
    *,
    runs: list[dict[str, Any]],
    plans: dict[str, tuple[dict[str, Any], ...]],
) -> dict[str, str]:
    return {
        str(run["id"]): str(run["current_stage"])
        for run in runs
        if str(run["current_stage"])
        and is_scoped_qa_stage(plans.get(str(run["id"]), ()), str(run["current_stage"]))
    }


def _qa_stage_members(
    conn: Any, *, run_ids: list[str], tables: _Tables
) -> dict[str, tuple[int, ...]]:
    """Every scoped-QA run's members in one read, for the shared stage walk."""
    if not run_ids or not tables.has("deployment_run_items"):
        return {}
    holes, params = _holes(conn, run_ids)
    members: dict[str, list[int]] = {}
    for raw in conn.execute(
        f"""SELECT run_id, item_id FROM deployment_run_items
             WHERE run_id IN ({holes}) ORDER BY run_id, item_id""",
        params,
    ).fetchall():
        row = row_dict(raw)
        members.setdefault(str(row["run_id"]), []).append(int(row["item_id"]))
    return {run_id: tuple(items) for run_id, items in members.items()}


def _resolved_decisions(
    conn: Any, *, runs: list[dict[str, Any]], tables: _Tables
) -> dict[str, dict[str, Any]]:
    if not tables.has("decision_requests"):
        return {}
    keys = [
        f"{run['id']}:{run['current_stage']}"
        for run in runs
        if str(run.get("current_stage") or "")
    ]
    if not keys:
        return {}
    by_key = {f"{run['id']}:{run['current_stage']}": str(run["id"]) for run in runs}
    holes, params = _holes(conn, keys)
    rows = conn.execute(
        f"""SELECT id, subject_key, resolution_action, resolved_at
              FROM decision_requests
             WHERE subject_type = 'deployment_stage'
               AND subject_key IN ({holes})
               AND status = 'resolved'""",
        params,
    ).fetchall()
    best: dict[str, tuple[datetime | None, int, dict[str, Any]]] = {}
    for raw in rows:
        row = row_dict(raw)
        key = str(row["subject_key"])
        resolved_at = parse_stamp(row.get("resolved_at"))
        request_id = int(row["id"])
        previous = best.get(key)
        key_order = (resolved_at is not None, resolved_at, request_id)
        if previous is None or key_order > (
            previous[0] is not None,
            previous[0],
            previous[1],
        ):
            best[key] = (
                resolved_at,
                request_id,
                {
                    "request_id": request_id,
                    "action": str(row.get("resolution_action") or ""),
                    "resolved_at": resolved_at,
                },
            )
    return {
        by_key[key]: payload
        for key, (_stamp, _id, payload) in best.items()
        if key in by_key
    }


def _completion_boundary(
    conn: Any, *, run_ids: list[str], tables: _Tables
) -> tuple[dict[str, tuple[str, ...]], dict[str, int]]:
    """Unpassed and total blocking obligations of runs off a scoped-QA stage.

    A run on a scoped-QA stage takes both counts from the stage gate instead.
    """
    if not run_ids or not (tables.has("qa_requirements") and tables.has("qa_runs")):
        return {}, {}
    holes, params = _holes(conn, run_ids)
    settled = settled_obligation_sql(conn, "r")
    rows = [
        row_dict(raw)
        for raw in conn.execute(
            f"""SELECT r.deployment_run_id, r.id, r.qa_kind,
                       EXISTS (SELECT 1 FROM qa_runs qr
                                WHERE qr.qa_requirement_id = r.id
                                  AND qr.verdict = 'pass') AS passed
                  FROM qa_requirements r
                 WHERE r.deployment_run_id IN ({holes})
                   AND r.blocking_mode = 'blocking'
                   AND NOT {settled}
                 ORDER BY r.deployment_run_id, r.id""",
            params,
        ).fetchall()
    ]
    totals: dict[str, int] = {}
    unpassed: list[dict[str, Any]] = []
    for row in rows:
        run_id = str(row["deployment_run_id"])
        totals[run_id] = totals.get(run_id, 0) + 1
        if not row["passed"]:
            unpassed.append(row)
    waits = requirements_awaiting_human_review(
        conn, (int(row["id"]) for row in unpassed)
    )
    unresolved: dict[str, list[str]] = {}
    for row in unpassed:
        waiting = waits.get(int(row["id"]))
        unresolved.setdefault(str(row["deployment_run_id"]), []).append(
            waiting.detail
            if waiting
            else f"requirement #{row['id']} ({row['qa_kind']}): no passing run"
        )
    return {k: tuple(v) for k, v in unresolved.items()}, totals


__all__ = [
    "LiveRunFactMaps",
    "live_deployment_runs",
    "load_live_run_facts",
    "probe_report_tables",
]
