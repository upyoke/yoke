"""Detailed QA-plan read model with case outcomes and evidence."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_catalog_reads import (
    PLAN_WITH_TARGET_ENVIRONMENT_SELECT,
    _attachment_rows,
    _capability_contexts,
    _outcome,
    _required_capability_details,
)
from yoke_core.domain.qa_method_capabilities import capability_kinds
from yoke_core.domain.schema_common import _table_exists


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _decode(value: Any, fallback: Any) -> Any:
    if isinstance(value, dict):
        return dict(value)
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
        "r.id AS run_id, r.performed_by, r.verdict, r.verdict_reason, "
        "r.execution_status, "
        "r.case_outcome, r.raw_result, "
        "r.capture_degraded_reason, "
        "COALESCE(r.completed_at, r.created_at, q.created_at) AS happened_at "
        "FROM qa_requirements q "
        "LEFT JOIN qa_runs r ON r.id=("
        "SELECT rr.id FROM qa_runs rr WHERE rr.qa_requirement_id=q.id "
        "ORDER BY rr.created_at DESC, rr.id DESC LIMIT 1"
        f") WHERE q.plan_id={marker} AND q.plan_case_key={marker} "
        f"AND COALESCE(q.host_baseline, '')={marker} "
        "AND q.waived_at IS NULL "
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
            "output_tail": None,
            "evidence": [],
        }
    raw_result = _decode(row["raw_result"], {})
    review = _review_state(conn, int(row["requirement_id"]), row)
    evidence_run_id = review["capture_run_id"] or row["run_id"]
    evidence = []
    if evidence_run_id is not None:
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
                (int(evidence_run_id),),
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
        "output_tail": (
            raw_result.get("output_tail") if isinstance(raw_result, dict) else None
        ),
        "evidence": evidence,
        "review": review,
    }


def _prior_agent_run(
    conn: Any,
    requirement_id: int,
    before_run_id: int,
) -> dict[str, Any] | None:
    marker = _placeholder(conn)
    return query_one(
        conn,
        "SELECT id,verdict,verdict_reason,raw_result FROM qa_runs "
        f"WHERE qa_requirement_id={marker} AND performed_by='agent' "
        f"AND id<{marker} ORDER BY id DESC LIMIT 1",
        (requirement_id, before_run_id),
    )


def _review_state(
    conn: Any,
    requirement_id: int,
    run: Any,
) -> dict[str, Any]:
    performed_by = str(run["performed_by"] or "")
    raw = _decode(run["raw_result"], {})
    rationale = run["verdict_reason"]
    capture_run_id = raw.get("capture_run_id") if isinstance(raw, dict) else None
    agent_verdict = run["verdict"] if performed_by == "agent" else None
    agent_run_id = int(run["run_id"]) if performed_by == "agent" else None
    if performed_by == "human_review" and run["run_id"] is not None:
        agent = _prior_agent_run(
            conn,
            requirement_id,
            int(run["run_id"]),
        )
        if agent is not None:
            agent_run_id = int(agent["id"])
            agent_raw = _decode(agent["raw_result"], {})
            capture_run_id = agent_raw.get("capture_run_id")
            agent_verdict = agent["verdict"]
            rationale = agent["verdict_reason"]
    request = None
    if performed_by in {"agent", "human_review"} and _table_exists(
        conn, "decision_requests"
    ):
        marker = _placeholder(conn)
        request_row = query_one(
            conn,
            "SELECT id,status,subject_context,resolution_action,"
            "resolution_note,resolved_at "
            "FROM decision_requests "
            "WHERE kind='qa_needs_review' AND subject_type='qa_requirement' "
            f"AND subject_key={marker} ORDER BY created_at DESC,id DESC LIMIT 1",
            (str(requirement_id),),
        )
        context = (
            _decode(request_row["subject_context"], {})
            if request_row is not None
            else {}
        )
        request_run_id = context.get("run_id")
        if (
            request_row is not None
            and agent_run_id is not None
            and str(request_run_id) == str(agent_run_id)
        ):
            request = {
                "id": int(request_row["id"]),
                "status": str(request_row["status"]),
                "resolution_action": request_row["resolution_action"],
                "resolution_note": request_row["resolution_note"],
                "resolved_at": request_row["resolved_at"],
            }
    if performed_by == "human_review":
        state = "human_review_resolved"
    elif performed_by == "agent" and run["verdict"] == "undetermined":
        state = (
            "human_review_requested"
            if request is not None and request["status"] == "pending"
            else "agent_undetermined"
        )
    elif performed_by == "agent":
        state = "agent_reviewed"
    elif run["case_outcome"] == "needs_review" or run["execution_status"] == "captured":
        state = "awaiting_agent_review"
    else:
        state = "not_applicable"
    return {
        "state": state,
        "capture_runner": (
            performed_by
            if performed_by in {"browser_substrate", "host_control"}
            else None
        ),
        "review_runner": (
            performed_by if performed_by in {"agent", "human_review"} else None
        ),
        "agent_verdict": agent_verdict,
        "rationale": rationale,
        "capture_run_id": (int(capture_run_id) if capture_run_id is not None else None),
        "decision_request": request,
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
        f"{PLAN_WITH_TARGET_ENVIRONMENT_SELECT} WHERE p.id={marker}",
        (int(plan_id),),
    )
    if row is None:
        raise LookupError(f"QA plan {plan_id} not found")
    from yoke_core.domain.qa_execution_environment_target import (
        resolve_plan_execution_target,
    )

    execution_target = resolve_plan_execution_target(
        conn,
        plan_id=int(plan_id),
        require_runtime_match=False,
        allow_unbound=True,
    )
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
        "SELECT c.*, m.name AS method_name, m.runner_id, "
        "m.required_capability_kinds, m.verdict_path "
        "FROM qa_plan_cases c JOIN qa_methods m ON m.id=c.method_id "
        f"WHERE c.plan_id={marker} ORDER BY c.position",
        (int(plan_id),),
    )
    capability_contexts = _capability_contexts(
        conn,
        project_id=int(row["project_id"]),
        capability_kinds={
            kind
            for case in case_rows
            for kind in capability_kinds(
                case["required_capability_kinds"],
                subject=f"method {case['method_id']!r}",
            )
        },
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
        required_kinds = capability_kinds(
            case["required_capability_kinds"],
            subject=f"method {case['method_id']!r}",
        )
        case_detail = {
            "id": int(case["id"]),
            "case_key": str(case["case_key"]),
            "position": int(case["position"]),
            "method_id": str(case["method_id"]),
            "method_name": str(case["method_name"]),
            "runner_id": str(case["runner_id"]),
            "required_capability_kinds": list(required_kinds),
            "required_capabilities": _required_capability_details(
                required_kinds,
                capability_contexts,
            ),
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
        "target_environment": row["target_environment"],
        "execution_target": execution_target,
        "cases": cases,
        "attachments": _attachment_rows(conn, int(plan_id)),
        "union": {"satisfied": satisfied, "counts": counts},
    }


__all__ = ["get_plan"]
