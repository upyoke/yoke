"""Bounded live-run status reads for one steering report request.

Facts are retrieved once for the live set; scoped QA uses qa_stage_outstanding.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain.deployment_flow_policy import QA_STEP_RUNNER, STAGE_KIND_QA
from yoke_core.domain.deployment_qa_case_failure_kinds import RED_VERDICTS
from yoke_core.domain.deployment_run_completion_preconditions import (
    RESOLVED_RUN_QA_STATUSES,
)
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.runs import TERMINAL_RUN_STATUSES
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_message_types import row_dict
from yoke_core.domain.steering_fleet_report_detectors import marker


_FACT_TABLES = (
    "deployment_runs",
    "deployment_flows",
    "deployment_stage_receipts",
    "qa_requirements",
    "qa_runs",
    "decision_requests",
    "deployment_run_qa",
)


@dataclass(frozen=True)
class LiveRunFactMaps:
    """One report request's live-run status facts, keyed by run id."""

    qa_stage_run_ids: frozenset[str]
    entered_at: dict[str, str]
    red: dict[str, tuple[dict[str, Any], ...]]
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
                   started_at, created_at, driver_attachment
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
    """Receipts, red verdicts, decisions, and completion-boundary counts."""
    run_ids = [str(run["id"]) for run in runs]
    if not run_ids:
        return LiveRunFactMaps(frozenset(), {}, {}, {}, {}, {})
    qa_stage_run_ids = _qa_stage_run_ids(conn, runs=runs, tables=tables)
    unresolved, totals = _completion_boundary(conn, run_ids=run_ids, tables=tables)
    return LiveRunFactMaps(
        qa_stage_run_ids=qa_stage_run_ids,
        entered_at=_latest_receipts(conn, runs=runs, tables=tables),
        red=_red_requirements(conn, run_ids=run_ids, tables=tables),
        decisions=_resolved_decisions(conn, runs=runs, tables=tables),
        unresolved=unresolved,
        totals=totals,
    )


def _holes(conn: Any, values: list[Any]) -> tuple[str, tuple[Any, ...]]:
    p = marker(conn)
    return ", ".join(p for _ in values), tuple(values)


def _qa_stage_run_ids(
    conn: Any, *, runs: list[dict[str, Any]], tables: _Tables
) -> frozenset[str]:
    if not tables.has("deployment_flows"):
        return frozenset()
    run_ids = [str(run["id"]) for run in runs]
    holes, params = _holes(conn, run_ids)
    rows = conn.execute(
        f"""SELECT dr.id, dr.current_stage, df.stages
              FROM deployment_runs dr
              JOIN deployment_flows df ON df.id = dr.flow
             WHERE dr.id IN ({holes})""",
        params,
    ).fetchall()
    found: set[str] = set()
    by_id = {str(run["id"]): str(run["current_stage"]) for run in runs}
    for raw in rows:
        row = row_dict(raw)
        run_id = str(row["id"])
        stage_name = by_id.get(run_id, "")
        if stage_name and _is_scoped_qa_stage(row.get("stages"), stage_name):
            found.add(run_id)
    return frozenset(found)


def _is_scoped_qa_stage(raw: Any, stage_name: str) -> bool:
    try:
        stages = json.loads(str(raw or "[]"))
    except (TypeError, ValueError):
        return False
    if not isinstance(stages, list):
        return False
    matches = [
        dict(stage)
        for stage in stages
        if isinstance(stage, Mapping) and str(stage.get("name") or "") == stage_name
    ]
    if len(matches) != 1:
        return False
    stage = matches[0]
    return (
        stage.get("stage_kind") == STAGE_KIND_QA
        and stage.get("step_runner") == QA_STEP_RUNNER
    )


def _latest_receipts(
    conn: Any, *, runs: list[dict[str, Any]], tables: _Tables
) -> dict[str, str]:
    if not tables.has("deployment_stage_receipts"):
        return {}
    run_ids = [str(run["id"]) for run in runs]
    wanted = {
        (str(run["id"]), str(run["current_stage"]))
        for run in runs
        if str(run["current_stage"])
    }
    if not wanted:
        return {}
    holes, params = _holes(conn, run_ids)
    rows = conn.execute(
        f"""SELECT run_id, stage_name, created_at, id
              FROM deployment_stage_receipts
             WHERE run_id IN ({holes})""",
        params,
    ).fetchall()
    best: dict[tuple[str, str], tuple[str, int]] = {}
    for raw in rows:
        row = row_dict(raw)
        key = (str(row["run_id"]), str(row["stage_name"] or ""))
        if key not in wanted:
            continue
        stamp = str(row.get("created_at") or "")
        receipt_id = int(row["id"])
        previous = best.get(key)
        if previous is None or (stamp, receipt_id) > previous:
            best[key] = (stamp, receipt_id)
    return {run_id: stamp for (run_id, _stage), (stamp, _id) in best.items() if stamp}


def _red_requirements(
    conn: Any, *, run_ids: list[str], tables: _Tables
) -> dict[str, tuple[dict[str, Any], ...]]:
    if not (tables.has("qa_requirements") and tables.has("qa_runs")):
        return {}
    holes, params = _holes(conn, run_ids)
    rows = conn.execute(
        f"""SELECT r.id, r.deployment_run_id,
                   (SELECT qr.verdict FROM qa_runs qr
                     WHERE qr.qa_requirement_id = r.id
                     ORDER BY qr.created_at DESC, qr.id DESC LIMIT 1) AS verdict,
                   p.slug, p.public_item_prefix, i.project_sequence
              FROM qa_requirements r
              LEFT JOIN items i ON i.id = r.deployment_member_item_id
              LEFT JOIN projects p ON p.id = i.project_id
             WHERE r.deployment_run_id IN ({holes})
               AND r.blocking_mode = 'blocking'
               AND r.waived_at IS NULL
               AND r.superseded_by_requirement_id IS NULL
             ORDER BY r.deployment_run_id, r.id""",
        params,
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {run_id: [] for run_id in run_ids}
    for raw in rows:
        row = row_dict(raw)
        verdict = str(row["verdict"] or "")
        if verdict not in RED_VERDICTS:
            continue
        ref = ""
        if row.get("project_sequence") is not None:
            ref = format_item_ref(
                row["slug"], row["public_item_prefix"], row["project_sequence"]
            )
        grouped[str(row["deployment_run_id"])].append(
            {"requirement_id": int(row["id"]), "verdict": verdict, "member_ref": ref}
        )
    return {run_id: tuple(items) for run_id, items in grouped.items() if items}


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
    best: dict[str, tuple[str, int, dict[str, Any]]] = {}
    for raw in rows:
        row = row_dict(raw)
        key = str(row["subject_key"])
        resolved_at = str(row.get("resolved_at") or "")
        request_id = int(row["id"])
        previous = best.get(key)
        if previous is None or (resolved_at, request_id) > previous[:2]:
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
    unresolved: dict[str, list[str]] = {run_id: [] for run_id in run_ids}
    totals: dict[str, int] = {run_id: 0 for run_id in run_ids}
    holes, params = _holes(conn, run_ids)
    if tables.has("deployment_run_qa"):
        resolved_holes, resolved_params = _holes(conn, list(RESOLVED_RUN_QA_STATUSES))
        flow_rows = conn.execute(
            f"""SELECT run_id, check_name, status FROM deployment_run_qa
                 WHERE run_id IN ({holes}) AND blocking=1
                   AND status NOT IN ({resolved_holes})
                 ORDER BY run_id, check_name""",
            params + resolved_params,
        ).fetchall()
        for raw in flow_rows:
            row = row_dict(raw)
            unresolved[str(row["run_id"])].append(
                f"check '{row['check_name']}' is {row['status']}"
            )
        for raw in conn.execute(
            f"""SELECT run_id, COUNT(*) AS total FROM deployment_run_qa
                 WHERE run_id IN ({holes}) AND blocking=1
                 GROUP BY run_id""",
            params,
        ).fetchall():
            row = row_dict(raw)
            totals[str(row["run_id"])] += int(row["total"] or 0)
    if tables.has("qa_requirements") and tables.has("qa_runs"):
        settled = settled_obligation_sql(conn, "r")
        plan_rows = conn.execute(
            f"""SELECT r.deployment_run_id, r.id, r.qa_kind FROM qa_requirements r
                 WHERE r.deployment_run_id IN ({holes})
                   AND r.blocking_mode = 'blocking'
                   AND NOT {settled}
                   AND NOT EXISTS (
                     SELECT 1 FROM qa_runs qr
                      WHERE qr.qa_requirement_id = r.id
                        AND qr.verdict = 'pass'
                   )
                 ORDER BY r.deployment_run_id, r.id""",
            params,
        ).fetchall()
        if plan_rows:
            from yoke_core.domain.qa_review_requests import (
                requirement_awaits_human_review,
            )

            for raw in plan_rows:
                row = row_dict(raw)
                waiting = requirement_awaits_human_review(conn, int(row["id"]))
                unresolved[str(row["deployment_run_id"])].append(
                    waiting.detail
                    if waiting
                    else f"requirement #{row['id']} ({row['qa_kind']}): no passing run"
                )
        for raw in conn.execute(
            f"""SELECT r.deployment_run_id AS run_id, COUNT(*) AS total
                  FROM qa_requirements r
                 WHERE r.deployment_run_id IN ({holes})
                   AND r.blocking_mode = 'blocking'
                   AND NOT {settled}
                 GROUP BY r.deployment_run_id""",
            params,
        ).fetchall():
            row = row_dict(raw)
            totals[str(row["run_id"])] += int(row["total"] or 0)
    return (
        {k: tuple(v) for k, v in unresolved.items() if v},
        {k: n for k, n in totals.items() if n},
    )


__all__ = [
    "LiveRunFactMaps",
    "live_deployment_runs",
    "load_live_run_facts",
    "probe_report_tables",
]
