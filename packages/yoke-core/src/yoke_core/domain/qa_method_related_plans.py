"""Method-scoped related-plan summaries for the QA catalog."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_execution_proof import qa_run_outcome


_RELATED_PLAN_STATE_ORDER = {
    "needs_review": 0,
    "passed": 1,
    "running": 2,
    "waiting": 3,
    "queued": 4,
    "failed": 5,
    "blocked_on_precondition": 6,
    "not_run": 7,
}
_SATISFIED_OUTCOMES = frozenset({"passed", "waived"})


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _declared_baselines(value: Any) -> list[str]:
    try:
        decoded = json.loads(str(value or "[]"))
    except (TypeError, ValueError):
        decoded = []
    if not isinstance(decoded, list):
        decoded = []
    baselines = [str(baseline) for baseline in decoded if baseline not in (None, "")]
    return list(dict.fromkeys(baselines))


def _latest_method_results(
    conn: Any,
    *,
    method_id: str,
    project_id: int | None,
) -> dict[tuple[int, str, str], Any]:
    marker = _placeholder(conn)
    params: tuple[Any, ...] = (method_id,)
    project_filter = ""
    if project_id is not None:
        project_filter = f"AND p.project_id={marker} "
        params += (project_id,)
    rows = query_rows(
        conn,
        "SELECT q.plan_id, q.plan_case_key, q.host_baseline, "
        "q.id, q.waived_at, r.verdict, r.case_outcome, "
        "COALESCE(r.completed_at, r.created_at, q.created_at) AS happened_at "
        "FROM qa_requirements q "
        "JOIN qa_plan_cases c ON c.plan_id=q.plan_id "
        "AND c.case_key=q.plan_case_key AND c.method_id=q.method_id "
        "JOIN qa_plans p ON p.id=q.plan_id "
        "LEFT JOIN qa_runs r ON r.id=("
        "SELECT rr.id FROM qa_runs rr "
        "WHERE rr.qa_requirement_id=q.id "
        "ORDER BY rr.created_at DESC, rr.id DESC LIMIT 1"
        ") "
        f"WHERE q.method_id={marker} AND p.retired_at IS NULL "
        + project_filter
        + "ORDER BY q.plan_id, q.plan_case_key, "
        "COALESCE(q.host_baseline, ''), happened_at DESC, q.id DESC",
        params,
    )
    latest: dict[tuple[int, str, str], Any] = {}
    for row in rows:
        key = (
            int(row["plan_id"]),
            str(row["plan_case_key"]),
            str(row["host_baseline"] or ""),
        )
        latest.setdefault(key, row)
    return latest


def _summary_state(counts: Mapping[str, int]) -> str:
    outcomes = set(counts)
    if outcomes and outcomes <= _SATISFIED_OUTCOMES:
        return "passed"
    if "failed" in outcomes:
        return "failed"
    if "needs_review" in outcomes:
        return "needs_review"
    if "blocked_on_precondition" in outcomes:
        return "blocked_on_precondition"
    if "running" in outcomes or outcomes & _SATISFIED_OUTCOMES:
        return "running"
    if "waiting" in outcomes:
        return "waiting"
    if "queued" in outcomes:
        return "queued"
    return "not_run"


def _ordered_plans(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        plans,
        key=lambda plan: (
            str(plan["project"]),
            str(plan["slug"]),
            int(plan["id"]),
        ),
    )
    ordered.sort(
        key=lambda plan: str(plan["outcome_summary"]["last_at"] or ""),
        reverse=True,
    )
    ordered.sort(key=lambda plan: not plan["method_is_complete_plan"])
    ordered.sort(
        key=lambda plan: _RELATED_PLAN_STATE_ORDER.get(
            str(plan["outcome_summary"]["state"]),
            len(_RELATED_PLAN_STATE_ORDER),
        ),
    )
    return ordered


def read_method_related_plans(
    conn: Any,
    *,
    method_id: str,
    project_id: int | None,
) -> list[dict[str, Any]]:
    """Return current method cases and their latest proof-slot rollups."""
    marker = _placeholder(conn)
    params: tuple[Any, ...] = (method_id,)
    project_filter = ""
    if project_id is not None:
        project_filter = f"AND p.project_id={marker} "
        params += (project_id,)
    rows = query_rows(
        conn,
        "SELECT p.id, p.slug, p.name, pr.slug AS project, "
        "c.id AS case_id, c.case_key, c.position, c.host_baselines, "
        "(SELECT COUNT(DISTINCT related.method_id) "
        "FROM qa_plan_cases related WHERE related.plan_id=p.id) "
        "AS plan_method_count "
        "FROM qa_plan_cases c "
        "JOIN qa_plans p ON p.id=c.plan_id "
        "JOIN projects pr ON pr.id=p.project_id "
        f"WHERE c.method_id={marker} AND p.retired_at IS NULL "
        + project_filter
        + "ORDER BY pr.slug, p.slug, p.id, c.position, c.id",
        params,
    )
    latest_results = (
        _latest_method_results(
            conn,
            method_id=method_id,
            project_id=project_id,
        )
        if rows
        else {}
    )
    plans: dict[int, dict[str, Any]] = {}
    for row in rows:
        plan_id = int(row["id"])
        plan = plans.setdefault(
            plan_id,
            {
                "id": plan_id,
                "slug": str(row["slug"]),
                "name": str(row["name"]),
                "project": str(row["project"]),
                "case_keys": [],
                "case_summaries": [],
                "plan_method_count": int(row["plan_method_count"]),
                "method_is_complete_plan": int(row["plan_method_count"]) == 1,
                "_case_key_set": set(),
                "_counts": {},
                "_last_at": None,
            },
        )
        case_key = str(row["case_key"])
        if case_key in plan["_case_key_set"]:
            continue
        plan["_case_key_set"].add(case_key)
        plan["case_keys"].append(case_key)
        host_baselines = _declared_baselines(row["host_baselines"])
        plan["case_summaries"].append(
            {
                "case_key": case_key,
                "host_baselines": host_baselines,
            }
        )
        for host_baseline in host_baselines or [None]:
            latest = latest_results.get(
                (plan_id, case_key, host_baseline or ""),
            )
            outcome = qa_run_outcome(latest) if latest is not None else "not_run"
            counts = plan["_counts"]
            counts[outcome] = counts.get(outcome, 0) + 1
            happened_at = latest["happened_at"] if latest is not None else None
            if happened_at is not None and (
                plan["_last_at"] is None or str(happened_at) > str(plan["_last_at"])
            ):
                plan["_last_at"] = happened_at
    result = []
    for plan in plans.values():
        counts = dict(plan.pop("_counts"))
        last_at = plan.pop("_last_at")
        plan.pop("_case_key_set")
        plan["outcome_summary"] = {
            "state": _summary_state(counts),
            "counts": counts,
            "last_at": last_at,
        }
        result.append(plan)
    return _ordered_plans(result)


__all__ = ["read_method_related_plans"]
