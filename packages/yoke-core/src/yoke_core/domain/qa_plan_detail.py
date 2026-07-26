"""Detailed QA-plan read model with case outcomes and evidence."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_catalog_reads import _attachment_rows, _outcome


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _decode(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback


def _case_result(conn: Any, plan_id: int, case_key: str) -> dict:
    marker = _placeholder(conn)
    row = query_one(
        conn,
        "SELECT q.id AS requirement_id, q.host_baseline, q.waived_at, "
        "r.id AS run_id, r.verdict, r.case_outcome, "
        "r.capture_degraded_reason, "
        "COALESCE(r.completed_at, r.created_at, q.created_at) AS happened_at "
        "FROM qa_requirements q "
        "LEFT JOIN qa_runs r ON r.id=("
        "SELECT rr.id FROM qa_runs rr WHERE rr.qa_requirement_id=q.id "
        "ORDER BY rr.created_at DESC, rr.id DESC LIMIT 1"
        f") WHERE q.plan_id={marker} AND q.plan_case_key={marker} "
        "ORDER BY happened_at DESC, q.id DESC LIMIT 1",
        (plan_id, case_key),
    )
    if row is None:
        return {
            "requirement_id": None,
            "run_id": None,
            "outcome": "not_run",
            "evidence": [],
        }
    evidence = []
    if row["run_id"] is not None:
        evidence = [
            {
                "id": int(artifact["id"]),
                "artifact_type": str(artifact["artifact_type"]),
                "content_type": artifact["content_type"],
                "artifact_handle": artifact["artifact_handle"],
                "metadata": _decode(artifact["metadata"], {}),
            }
            for artifact in query_rows(
                conn,
                "SELECT id, artifact_type, content_type, artifact_handle, "
                f"metadata FROM qa_artifacts WHERE qa_run_id={marker} "
                "ORDER BY id",
                (int(row["run_id"]),),
            )
        ]
    return {
        "requirement_id": int(row["requirement_id"]),
        "run_id": int(row["run_id"]) if row["run_id"] is not None else None,
        "host_baseline": row["host_baseline"],
        "outcome": _outcome(row),
        "capture_degraded_reason": row["capture_degraded_reason"],
        "happened_at": row["happened_at"],
        "evidence": evidence,
    }


def get_plan(conn: Any, *, plan_id: int) -> dict:
    """Return one plan with ordered cases, attachments and union verdict."""
    marker = _placeholder(conn)
    row = query_one(
        conn,
        "SELECT p.*, pr.slug AS project FROM qa_plans p "
        "JOIN projects pr ON pr.id=p.project_id "
        f"WHERE p.id={marker}",
        (int(plan_id),),
    )
    if row is None:
        raise LookupError(f"QA plan {plan_id} not found")
    cases = []
    for case in query_rows(
        conn,
        "SELECT c.*, m.name AS method_name, m.executor_id, "
        "m.required_capability_kind, m.verdict_path "
        "FROM qa_plan_cases c JOIN qa_methods m ON m.id=c.method_id "
        f"WHERE c.plan_id={marker} ORDER BY c.position",
        (int(plan_id),),
    ):
        cases.append({
            "id": int(case["id"]),
            "case_key": str(case["case_key"]),
            "position": int(case["position"]),
            "method_id": str(case["method_id"]),
            "method_name": str(case["method_name"]),
            "executor_id": str(case["executor_id"]),
            "required_capability_kind": case["required_capability_kind"],
            "verdict_path": str(case["verdict_path"]),
            "instructions": str(case["instructions"]),
            "expected_outcome": str(case["expected_outcome"]),
            "method_config": _decode(case["method_config"], {}),
            "success_policy_id": case["success_policy_id"],
            "success_policy_params": _decode(
                case["success_policy_params"], None,
            ),
            "host_baselines": _decode(case["host_baselines"], []),
            "entry_surface": case["entry_surface"],
            "required_completion": case["required_completion"],
            "last_result": _case_result(
                conn, int(plan_id), str(case["case_key"]),
            ),
        })
    counts: dict[str, int] = {}
    for case in cases:
        outcome = str(case["last_result"]["outcome"])
        counts[outcome] = counts.get(outcome, 0) + 1
    satisfied = bool(cases) and all(
        case["last_result"]["outcome"] in {"passed", "waived"}
        for case in cases
    )
    return {
        "id": int(row["id"]),
        "project": str(row["project"]),
        "project_id": int(row["project_id"]),
        "slug": str(row["slug"]),
        "name": str(row["name"]),
        "description": str(row["description"]),
        "success_policy_id": str(row["success_policy_id"]),
        "success_policy_params": _decode(row["success_policy_params"], {}),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "retired_at": row["retired_at"],
        "cases": cases,
        "attachments": _attachment_rows(conn, int(plan_id)),
        "union": {"satisfied": satisfied, "counts": counts},
    }


__all__ = ["get_plan"]
