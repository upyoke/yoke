"""Recent QA plan activity rows and daily outcome summaries."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from typing import Any, Iterable, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.qa_execution_proof import (
    qa_artifact_rows_by_run,
    qa_evidence_run_id,
    qa_precondition_reason,
    qa_proof_summary,
    qa_run_outcome,
)
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_activity_selection import (
    HAPPENED_AT,
    activity_query,
    bound_groups,
    item_filter,
    run_group_filter,
)


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
    item_ids: Optional[Iterable[int]] = None,
    deployment_run_ids: Optional[Iterable[str]] = None,
    limit: int = 100,
) -> tuple[list[dict], Optional[dict[str, Any]]]:
    """Return activity rows, and how an item-scoped read was bounded.

    Without ``item_ids`` the read is a recency page over the whole scope and
    ``limit`` caps it. With ``item_ids`` that page would be a defect rather
    than a page: one busy subject filling the cap would silently hide every
    other requested subject, so a card would report an item as having no
    evidence and no waiting review when it has both. There ``limit`` bounds
    each item's checks WITHIN each deployment run they name, and its run-less
    checks as their own group, so neither another item nor another release
    can take the rows a given card needs. The second return value names the
    cap and exactly which items hit it — measured by fetching one row past
    the cap, never inferred from a full-looking page. What is dropped is an
    item's older history inside one run group; a caller that must not lose a
    current request joins those independently rather than through these rows.
    """
    marker = _placeholder(conn)
    params: list[Any] = []
    where = "WHERE q.plan_id IS NOT NULL"
    if identity is not None:
        where += f" AND p.project_id={marker}"
        params.append(int(identity.id))
    if deployment_run_id is not None:
        where += f" AND q.deployment_run_id={marker}"
        params.append(deployment_run_id)
    where += item_filter(marker, params, item_ids)
    where += run_group_filter(marker, params, deployment_run_ids)
    bounded = max(1, min(int(limit), 500))
    item_scoped = item_ids is not None
    params.append(bounded + 1 if item_scoped else bounded)
    rows = query_rows(
        conn,
        activity_query(marker, where, item_scoped=item_scoped),
        tuple(params),
    )
    selection: Optional[dict[str, Any]] = None
    if item_scoped:
        rows, selection = bound_groups(rows, bounded)
    # A review row rarely captures its own evidence — it embeds a
    # capture_run_id back to the immutable run that did — so evidence is
    # resolved through the same shared chain the item and plan detail pages
    # use, rather than stopping at each row's own (often empty) run.
    evidence_run_ids = [
        (
            qa_evidence_run_id(
                conn,
                requirement_id=int(row["requirement_id"]),
                run_id=int(row["run_id"]) if row["run_id"] is not None else None,
                performed_by=row["performed_by"],
                raw_result=row["raw_result"],
            )
            if row["run_id"] is not None
            else None
        )
        for row in rows
    ]
    artifact_rows = qa_artifact_rows_by_run(
        conn, {rid for rid in evidence_run_ids if rid is not None}
    )
    result = []
    for row, evidence_run_id in zip(rows, evidence_run_ids):
        raw_result = _json_value(row["raw_result"], {})
        run_id = int(row["run_id"]) if row["run_id"] is not None else None
        precondition_reason = qa_precondition_reason(raw_result)
        outcome = qa_run_outcome(row)
        artifacts = artifact_rows.get(evidence_run_id, [])
        artifact_counts = Counter(a["artifact_type"] for a in artifacts)
        result.append(
            {
                "requirement_id": int(row["requirement_id"]),
                "run_id": run_id,
                "deployment_run_id": row["deployment_run_id"],
                "deployment_stage": row["deployment_stage"],
                "item_id": (
                    int(row["item_id"]) if row["item_id"] is not None else None
                ),
                "deployment_member_item_id": (
                    int(row["deployment_member_item_id"])
                    if row["deployment_member_item_id"] is not None
                    else None
                ),
                "plan_id": int(row["plan_id"]),
                "plan": str(row["plan"]),
                "project": str(row["project"]),
                "case_key": str(row["plan_case_key"]),
                "host_baseline": row["host_baseline"],
                "method_id": row["method_id"],
                "method_name": row["method_name"],
                "outcome": outcome,
                "artifacts": artifacts,
                "evidence_count": len(artifacts),
                "capture_degraded_reason": row["capture_degraded_reason"],
                "verdict_reason": row["verdict_reason"],
                "precondition_reason": precondition_reason,
                "proof_summary": qa_proof_summary(
                    method_id=row["method_id"],
                    run_id=run_id,
                    raw_result=raw_result,
                    artifacts=artifact_counts,
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
    return result, selection


def _activity_summary(
    conn: Any,
    *,
    identity: Optional[Any],
    deployment_run_id: Optional[str],
    item_ids: Optional[Iterable[int]],
    day: Optional[date],
) -> dict[str, Any]:
    activity_day = day or datetime.now(timezone.utc).date()
    next_day = activity_day + timedelta(days=1)
    marker = _placeholder(conn)
    params: list[Any] = []
    where = "WHERE q.plan_id IS NOT NULL"
    if identity is not None:
        where += f" AND p.project_id={marker}"
        params.append(int(identity.id))
    if deployment_run_id is not None:
        where += f" AND q.deployment_run_id={marker}"
        params.append(deployment_run_id)
    where += item_filter(marker, params, item_ids)
    where += f" AND {HAPPENED_AT}>={marker} AND {HAPPENED_AT}<{marker}"
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
    item_ids: Optional[Iterable[int]] = None,
    deployment_run_ids: Optional[Iterable[str]] = None,
    limit: int = 100,
) -> list[dict]:
    """Return the rows alone; ``read_activity`` carries the bounding facts."""
    return _list_activity(
        conn,
        identity=_project_row(conn, project),
        deployment_run_id=deployment_run_id,
        item_ids=item_ids,
        deployment_run_ids=deployment_run_ids,
        limit=limit,
    )[0]


def read_activity(
    conn: Any,
    *,
    project: Optional[str] = None,
    deployment_run_id: Optional[str] = None,
    item_ids: Optional[Iterable[int]] = None,
    deployment_run_ids: Optional[Iterable[str]] = None,
    limit: int = 100,
    day: Optional[date] = None,
) -> dict[str, Any]:
    """Return recent rows plus untruncated outcome counts for one UTC day."""
    identity = _project_row(conn, project)
    rows, selection = _list_activity(
        conn,
        identity=identity,
        deployment_run_id=deployment_run_id,
        item_ids=item_ids,
        deployment_run_ids=deployment_run_ids,
        limit=limit,
    )
    return {
        "rows": rows,
        "item_selection": selection,
        "summary": _activity_summary(
            conn,
            identity=identity,
            deployment_run_id=deployment_run_id,
            item_ids=item_ids,
            day=day,
        ),
    }


__all__ = ["list_activity", "read_activity"]
