"""Detailed QA-plan read model with case outcomes and evidence."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_catalog_reads import (
    _attachment_rows,
    _capability_contexts,
    _outcome,
)


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _decode(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback


def _case_result(
    conn: Any,
    plan_id: int,
    case_key: str,
    host_baseline: str | None,
    deployment_run_id: str | None,
) -> dict:
    marker = _placeholder(conn)
    deployment_filter = ""
    params: tuple[Any, ...] = (plan_id, case_key, host_baseline or "")
    if deployment_run_id is not None:
        deployment_filter = f" AND q.deployment_run_id={marker}"
        params += (deployment_run_id,)
    row = query_one(
        conn,
        "SELECT q.id AS requirement_id, q.host_baseline, "
        "q.deployment_run_id, q.waived_at, "
        "r.id AS run_id, r.verdict, r.case_outcome, "
        "r.capture_degraded_reason, "
        "COALESCE(r.completed_at, r.created_at, q.created_at) AS happened_at "
        "FROM qa_requirements q "
        "LEFT JOIN qa_runs r ON r.id=("
        "SELECT rr.id FROM qa_runs rr WHERE rr.qa_requirement_id=q.id "
        "ORDER BY rr.created_at DESC, rr.id DESC LIMIT 1"
        f") WHERE q.plan_id={marker} AND q.plan_case_key={marker} "
        f"AND COALESCE(q.host_baseline, '')={marker} "
        f"{deployment_filter} "
        "ORDER BY happened_at DESC, q.id DESC LIMIT 1",
        params,
    )
    if row is None:
        return {
            "requirement_id": None,
            "run_id": None,
            "deployment_run_id": deployment_run_id,
            "host_baseline": host_baseline,
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
        "deployment_run_id": row["deployment_run_id"],
        "host_baseline": row["host_baseline"],
        "outcome": _outcome(row),
        "capture_degraded_reason": row["capture_degraded_reason"],
        "happened_at": row["happened_at"],
        "evidence": evidence,
    }


def get_plan(
    conn: Any,
    *,
    plan_id: int,
    deployment_run_id: str | None = None,
) -> dict:
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
    if deployment_run_id is not None:
        run = query_one(
            conn,
            f"SELECT project_id FROM deployment_runs WHERE id={marker}",
            (deployment_run_id,),
        )
        if run is None or int(run["project_id"]) != int(row["project_id"]):
            raise LookupError(
                f"deployment run {deployment_run_id!r} not found for QA plan {plan_id}"
            )
    case_rows = query_rows(
        conn,
        "SELECT c.*, m.name AS method_name, m.executor_id, "
        "m.required_capability_kind, m.verdict_path "
        "FROM qa_plan_cases c JOIN qa_methods m ON m.id=c.method_id "
        f"WHERE c.plan_id={marker} ORDER BY c.position",
        (int(plan_id),),
    )
    capability_contexts = _capability_contexts(
        conn,
        project_id=int(row["project_id"]),
        capability_kinds={case["required_capability_kind"] for case in case_rows},
    )
    cases = []
    proofs = []
    for case in case_rows:
        host_baselines = _decode(case["host_baselines"], [])
        case_proofs = [
            _case_result(
                conn,
                int(plan_id),
                str(case["case_key"]),
                host_baseline,
                deployment_run_id,
            )
            for host_baseline in (host_baselines or [None])
        ]
        capability_kind = case["required_capability_kind"]
        capability_context = dict(capability_contexts[capability_kind])
        case_detail = {
            "id": int(case["id"]),
            "case_key": str(case["case_key"]),
            "position": int(case["position"]),
            "method_id": str(case["method_id"]),
            "method_name": str(case["method_name"]),
            "executor_id": str(case["executor_id"]),
            "required_capability_kind": capability_kind,
            "capability_state": capability_context["state"],
            "capability_context": capability_context,
            "verdict_path": str(case["verdict_path"]),
            "instructions": str(case["instructions"]),
            "expected_outcome": str(case["expected_outcome"]),
            "method_config": _decode(case["method_config"], {}),
            "success_policy_id": case["success_policy_id"],
            "success_policy_params": _decode(
                case["success_policy_params"],
                None,
            ),
            "host_baselines": host_baselines,
            "entry_surface": case["entry_surface"],
            "required_completion": case["required_completion"],
            "proofs": case_proofs,
        }
        if not host_baselines:
            case_detail["last_result"] = case_proofs[0]
        cases.append(case_detail)
        proofs.extend(case_proofs)
    counts: dict[str, int] = {}
    for proof in proofs:
        outcome = str(proof["outcome"])
        counts[outcome] = counts.get(outcome, 0) + 1
    satisfied = bool(proofs) and all(
        proof["outcome"] in {"passed", "waived"} for proof in proofs
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
        "deployment_run_id": deployment_run_id,
        "cases": cases,
        "attachments": _attachment_rows(conn, int(plan_id)),
        "union": {"satisfied": satisfied, "counts": counts},
    }


__all__ = ["get_plan"]
