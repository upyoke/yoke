"""Recent QA plan activity rows and daily outcome summaries."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.qa_execution_proof import (
    qa_artifact_counts_by_run,
    qa_precondition_reason,
    qa_proof_summary,
    qa_run_outcome,
)
from yoke_core.domain.db_helpers import query_rows


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _json_value(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback


def _project_row(conn: Any, project: Optional[str]) -> Optional[Any]:
    if project is None:
        return None
    identity = resolve_project(conn, project, required=False)
    if identity is None:
        raise LookupError(f"project {project!r} not found")
    return identity


def _list_activity(
    conn: Any,
    *,
    identity: Optional[Any],
    deployment_run_id: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    marker = _placeholder(conn)
    params: list[Any] = []
    where = "WHERE q.plan_id IS NOT NULL"
    if identity is not None:
        where += f" AND p.project_id={marker}"
        params.append(int(identity.id))
    if deployment_run_id is not None:
        where += f" AND q.deployment_run_id={marker}"
        params.append(deployment_run_id)
    params.append(max(1, min(int(limit), 500)))
    rows = query_rows(
        conn,
        "SELECT q.id AS requirement_id, q.plan_id, q.plan_case_key, "
        "q.deployment_run_id, "
        "q.host_baseline, q.waived_at, p.slug AS plan, pr.slug AS project, "
        "q.method_id, q.method_name, m.proof_kind, r.id AS run_id, "
        "r.verdict, r.verdict_reason, r.case_outcome, r.capture_degraded_reason, "
        "r.raw_result, "
        "COALESCE(r.completed_at, r.created_at, q.created_at) AS happened_at, "
        "(SELECT COUNT(*) FROM qa_artifacts a WHERE a.qa_run_id=r.id) "
        "AS evidence_count "
        "FROM qa_requirements q JOIN qa_plans p ON p.id=q.plan_id "
        "JOIN projects pr ON pr.id=p.project_id "
        "LEFT JOIN qa_methods m ON m.id=q.method_id "
        "LEFT JOIN qa_runs r ON r.id=("
        "SELECT rr.id FROM qa_runs rr WHERE rr.qa_requirement_id=q.id "
        "ORDER BY rr.created_at DESC, rr.id DESC LIMIT 1"
        f") {where} ORDER BY happened_at DESC, q.id DESC LIMIT {marker}",
        tuple(params),
    )
    artifacts_by_run = qa_artifact_counts_by_run(
        conn,
        {int(row["run_id"]) for row in rows if row["run_id"] is not None},
    )
    result = []
    for row in rows:
        raw_result = _json_value(row["raw_result"], {})
        run_id = int(row["run_id"]) if row["run_id"] is not None else None
        precondition_reason = qa_precondition_reason(raw_result)
        outcome = qa_run_outcome(row)
        result.append(
            {
                "requirement_id": int(row["requirement_id"]),
                "run_id": run_id,
                "deployment_run_id": row["deployment_run_id"],
                "plan_id": int(row["plan_id"]),
                "plan": str(row["plan"]),
                "project": str(row["project"]),
                "case_key": str(row["plan_case_key"]),
                "host_baseline": row["host_baseline"],
                "method_id": row["method_id"],
                "method_name": row["method_name"],
                "outcome": outcome,
                "evidence_count": int(row["evidence_count"] or 0),
                "capture_degraded_reason": row["capture_degraded_reason"],
                "verdict_reason": row["verdict_reason"],
                "precondition_reason": precondition_reason,
                "proof_summary": qa_proof_summary(
                    method_id=row["method_id"],
                    run_id=run_id,
                    raw_result=raw_result,
                    artifacts=artifacts_by_run.get(run_id, {}),
                    outcome=outcome,
                    verdict_reason=row["verdict_reason"],
                    capture_degraded_reason=row["capture_degraded_reason"],
                    host_baseline=row["host_baseline"],
                    precondition_reason=precondition_reason,
                    proof_kind=row["proof_kind"],
                ),
                "happened_at": row["happened_at"],
            }
        )
    return result


def _activity_summary(
    conn: Any,
    *,
    identity: Optional[Any],
    deployment_run_id: Optional[str],
    day: Optional[date],
) -> dict[str, Any]:
    activity_day = day or datetime.now(timezone.utc).date()
    next_day = activity_day + timedelta(days=1)
    marker = _placeholder(conn)
    happened_at = "COALESCE(r.completed_at, r.created_at, q.created_at)"
    params: list[Any] = []
    where = "WHERE q.plan_id IS NOT NULL"
    if identity is not None:
        where += f" AND p.project_id={marker}"
        params.append(int(identity.id))
    if deployment_run_id is not None:
        where += f" AND q.deployment_run_id={marker}"
        params.append(deployment_run_id)
    where += f" AND {happened_at}>={marker} AND {happened_at}<{marker}"
    params.extend([activity_day.isoformat(), next_day.isoformat()])
    rows = query_rows(
        conn,
        "SELECT q.waived_at, r.verdict, r.case_outcome "
        "FROM qa_requirements q JOIN qa_plans p ON p.id=q.plan_id "
        "LEFT JOIN qa_runs r ON r.id=("
        "SELECT rr.id FROM qa_runs rr WHERE rr.qa_requirement_id=q.id "
        "ORDER BY rr.created_at DESC, rr.id DESC LIMIT 1"
        f") {where}",
        tuple(params),
    )
    counts = Counter(qa_run_outcome(row) for row in rows)
    return {
        "day": activity_day.isoformat(),
        "total": len(rows),
        "counts": dict(sorted(counts.items())),
    }


def list_activity(
    conn: Any,
    *,
    project: Optional[str] = None,
    deployment_run_id: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    return _list_activity(
        conn,
        identity=_project_row(conn, project),
        deployment_run_id=deployment_run_id,
        limit=limit,
    )


def read_activity(
    conn: Any,
    *,
    project: Optional[str] = None,
    deployment_run_id: Optional[str] = None,
    limit: int = 100,
    day: Optional[date] = None,
) -> dict[str, Any]:
    """Return recent rows plus untruncated outcome counts for one UTC day."""
    identity = _project_row(conn, project)
    return {
        "rows": _list_activity(
            conn,
            identity=identity,
            deployment_run_id=deployment_run_id,
            limit=limit,
        ),
        "summary": _activity_summary(
            conn,
            identity=identity,
            deployment_run_id=deployment_run_id,
            day=day,
        ),
    }


__all__ = ["list_activity", "read_activity"]
