"""Detailed QA-plan read model with case outcomes and evidence."""

from __future__ import annotations

from typing import Any

from yoke_contracts.qa_case_starting_state import stored_fan_out
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_catalog_reads import (
    PLAN_WITH_TARGET_ENVIRONMENT_SELECT,
    _attachment_rows,
    _capability_contexts,
    _required_capability_details,
)
from yoke_core.domain.qa_method_capabilities import capability_kinds
from yoke_core.domain.qa_plan_case_proof import _case_result, _decode, _placeholder


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
    case_rows = [
        {**case, "host_baselines": _decode(case["host_baselines"], [])}
        for case in case_rows
    ]
    for case, fan_out in zip(case_rows, stored_fan_out(case_rows)):
        host_baselines = case["host_baselines"]
        case_proofs = [
            _case_result(
                conn,
                int(plan_id),
                str(case["case_key"]),
                host_baseline,
                deployment_run_id,
                target_env,
            )
            for host_baseline in fan_out
            for target_env in (_decode(case["target_envs"], []) or [None])
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
            "starting_state": case["starting_state"],
            "starting_state_reason": case["starting_state_reason"],
            "target_envs": _decode(case["target_envs"], []),
            "entry_surface": case["entry_surface"],
            "required_completion": case["required_completion"],
            "proofs": case_proofs,
        }
        if fan_out == [None] and len(case_proofs) == 1:
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
