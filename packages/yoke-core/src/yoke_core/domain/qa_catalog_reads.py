"""Read models for the QA method, plan, and activity experience."""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one, query_rows, query_scalar
from yoke_core.domain.project_identity import resolve_project


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


def _capability_state(
    conn: Any,
    *,
    project_id: Optional[int],
    capability_kind: Optional[str],
) -> str:
    if capability_kind is None:
        return "available"
    if project_id is None:
        return "project_scoped"
    marker = _placeholder(conn)
    row = query_one(
        conn,
        "SELECT verified_at FROM project_capabilities "
        f"WHERE project_id={marker} AND type={marker}",
        (project_id, capability_kind),
    )
    if row is None:
        return "not_configured"
    if row["verified_at"]:
        return "ready"
    return "configured"


def list_methods(conn: Any, *, project: Optional[str] = None) -> list[dict]:
    """Return contracts plus derived usage and capability availability."""
    identity = _project_row(conn, project)
    project_id = int(identity.id) if identity is not None else None
    marker = _placeholder(conn)
    rows = query_rows(
        conn,
        "SELECT * FROM qa_methods "
        "WHERE project_id IS NULL"
        + (f" OR project_id={marker}" if project_id is not None else "")
        + " ORDER BY "
        "CASE WHEN required_capability_kind IS NULL THEN 0 "
        "WHEN required_capability_kind='browser-control' THEN 1 ELSE 2 END, "
        "name",
        (project_id,) if project_id is not None else (),
    )
    result = []
    for row in rows:
        count_params: tuple = (row["id"],)
        count_sql = (
            "SELECT COUNT(DISTINCT c.plan_id) "
            "FROM qa_plan_cases c JOIN qa_plans p ON p.id=c.plan_id "
            f"WHERE c.method_id={marker} AND p.retired_at IS NULL"
        )
        if project_id is not None:
            count_sql += f" AND p.project_id={marker}"
            count_params += (project_id,)
        used_by = int(query_scalar(conn, count_sql, count_params) or 0)
        result.append({
            "id": str(row["id"]),
            "name": str(row["name"]),
            "description": str(row["description"]),
            "source_kind": str(row["source_kind"]),
            "source_ref": row["source_ref"],
            "executor_id": str(row["executor_id"]),
            "required_capability_kind": row["required_capability_kind"],
            "verdict_path": str(row["verdict_path"]),
            "verdict_contract": str(row["verdict_contract"]),
            "evidence_contract": str(row["evidence_contract"]),
            "success_policy_id": str(row["success_policy_id"]),
            "success_policy_params": _json_value(
                row["success_policy_params"], {},
            ),
            "concurrency_mode": str(row["concurrency_mode"]),
            "used_by_plan_count": used_by,
            "capability_state": _capability_state(
                conn,
                project_id=project_id,
                capability_kind=row["required_capability_kind"],
            ),
        })
    return result


def get_method(
    conn: Any, *, method_id: str, project: Optional[str] = None,
) -> dict:
    rows = list_methods(conn, project=project)
    method = next((row for row in rows if row["id"] == method_id), None)
    if method is None:
        raise LookupError(f"QA method {method_id!r} not found")
    marker = _placeholder(conn)
    plan_rows = query_rows(
        conn,
        "SELECT p.id, p.slug, p.name, pr.slug AS project, "
        "c.case_key FROM qa_plan_cases c "
        "JOIN qa_plans p ON p.id=c.plan_id "
        "JOIN projects pr ON pr.id=p.project_id "
        f"WHERE c.method_id={marker} AND p.retired_at IS NULL "
        "ORDER BY pr.slug, p.slug, c.position",
        (method_id,),
    )
    plans: dict[int, dict] = {}
    for row in plan_rows:
        plan = plans.setdefault(int(row["id"]), {
            "id": int(row["id"]),
            "slug": str(row["slug"]),
            "name": str(row["name"]),
            "project": str(row["project"]),
            "case_keys": [],
        })
        plan["case_keys"].append(str(row["case_key"]))
    return {**method, "plans": list(plans.values())}


def _latest_requirement_outcome(conn: Any, plan_id: int) -> tuple:
    marker = _placeholder(conn)
    row = query_one(
        conn,
        "SELECT q.id, q.waived_at, r.verdict, r.case_outcome, "
        "COALESCE(r.completed_at, r.created_at, q.created_at) AS happened_at "
        "FROM qa_requirements q "
        "LEFT JOIN qa_runs r ON r.id=("
        "SELECT rr.id FROM qa_runs rr "
        "WHERE rr.qa_requirement_id=q.id "
        "ORDER BY rr.created_at DESC, rr.id DESC LIMIT 1"
        ") "
        f"WHERE q.plan_id={marker} "
        "ORDER BY happened_at DESC, q.id DESC LIMIT 1",
        (plan_id,),
    )
    if row is None:
        return (None, None)
    return (_outcome(row), row["happened_at"])


def _attachment_rows(conn: Any, plan_id: int) -> list[dict]:
    marker = _placeholder(conn)
    project_defaults = query_rows(
        conn,
        "SELECT 'project_default' AS kind, p.slug AS project, "
        "d.workflow_id, d.transition_id, NULL AS item_id "
        "FROM qa_plan_project_defaults d "
        "JOIN projects p ON p.id=d.project_id "
        f"WHERE d.plan_id={marker} "
        "ORDER BY p.slug, d.workflow_id, d.transition_id",
        (plan_id,),
    )
    item_attachments = query_rows(
        conn,
        "SELECT 'item' AS kind, p.slug AS project, "
        "i.workflow_id, a.transition_id, i.id AS item_id "
        "FROM qa_plan_item_attachments a "
        "JOIN items i ON i.id=a.item_id "
        "JOIN projects p ON p.id=i.project_id "
        f"WHERE a.plan_id={marker} "
        "ORDER BY p.slug, i.id, a.transition_id",
        (plan_id,),
    )
    return [dict(row) for row in (*project_defaults, *item_attachments)]


def list_plans(conn: Any, *, project: Optional[str] = None) -> list[dict]:
    identity = _project_row(conn, project)
    marker = _placeholder(conn)
    params: tuple = ()
    where = "WHERE p.retired_at IS NULL"
    if identity is not None:
        where += f" AND p.project_id={marker}"
        params = (int(identity.id),)
    rows = query_rows(
        conn,
        "SELECT p.*, pr.slug AS project FROM qa_plans p "
        f"JOIN projects pr ON pr.id=p.project_id {where} "
        "ORDER BY pr.slug, p.slug",
        params,
    )
    result = []
    for row in rows:
        plan_id = int(row["id"])
        cases = query_rows(
            conn,
            "SELECT method_id, host_baselines FROM qa_plan_cases "
            f"WHERE plan_id={marker} ORDER BY position",
            (plan_id,),
        )
        materialized_count = sum(
            max(1, len(_json_value(case["host_baselines"], [])))
            for case in cases
        )
        last_outcome, last_at = _latest_requirement_outcome(conn, plan_id)
        result.append({
            "id": plan_id,
            "project": str(row["project"]),
            "slug": str(row["slug"]),
            "name": str(row["name"]),
            "description": str(row["description"]),
            "case_count": len(cases),
            "materialized_requirement_count": materialized_count,
            "method_ids": list(dict.fromkeys(
                str(case["method_id"]) for case in cases
            )),
            "attachments": _attachment_rows(conn, plan_id),
            "last_outcome": last_outcome,
            "last_at": last_at,
        })
    return result


def _outcome(row: Any) -> str:
    if row["waived_at"]:
        return "waived"
    if row["case_outcome"]:
        return str(row["case_outcome"])
    verdict = row["verdict"]
    if verdict == "pass":
        return "passed"
    if verdict in {"fail", "error"}:
        return "failed"
    if verdict == "inconclusive":
        return "needs_review"
    return "queued"


def list_activity(
    conn: Any,
    *,
    project: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    identity = _project_row(conn, project)
    marker = _placeholder(conn)
    params: list[Any] = []
    where = "WHERE q.plan_id IS NOT NULL"
    if identity is not None:
        where += f" AND p.project_id={marker}"
        params.append(int(identity.id))
    params.append(max(1, min(int(limit), 500)))
    rows = query_rows(
        conn,
        "SELECT q.id AS requirement_id, q.plan_id, q.plan_case_key, "
        "q.host_baseline, q.waived_at, p.slug AS plan, pr.slug AS project, "
        "m.id AS method_id, m.name AS method_name, r.id AS run_id, "
        "r.verdict, r.case_outcome, r.capture_degraded_reason, "
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
    return [{
        "requirement_id": int(row["requirement_id"]),
        "run_id": int(row["run_id"]) if row["run_id"] is not None else None,
        "plan_id": int(row["plan_id"]),
        "plan": str(row["plan"]),
        "project": str(row["project"]),
        "case_key": str(row["plan_case_key"]),
        "host_baseline": row["host_baseline"],
        "method_id": row["method_id"],
        "method_name": row["method_name"],
        "outcome": _outcome(row),
        "evidence_count": int(row["evidence_count"] or 0),
        "capture_degraded_reason": row["capture_degraded_reason"],
        "happened_at": row["happened_at"],
    } for row in rows]


__all__ = [
    "get_method",
    "list_activity",
    "list_methods",
    "list_plans",
]
