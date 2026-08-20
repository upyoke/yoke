"""Idempotent QA requirement writes for materialized plan cases."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Optional

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_management import QaPlanError, _json, _placeholder
from yoke_core.domain.qa_method_capabilities import encoded_capability_kinds
from yoke_core.domain.qa_execution_environment_target import (
    canonical_target,
    require_case_target,
    target_digest,
)


def require_existing_target(
    rows: Iterable[Mapping[str, Any]],
    *,
    execution_target: Mapping[str, Any],
    subject: str,
) -> list[int]:
    """Permit idempotent reuse only for rows bound to the exact target."""
    expected_json = canonical_target(execution_target)
    expected_digest = target_digest(execution_target)
    ids: list[int] = []
    for row in rows:
        requirement_id = int(row["id"])
        raw_target = row["execution_target_json"]
        stored_digest = str(row["execution_target_digest"] or "")
        if not raw_target or not stored_digest:
            raise QaPlanError(
                f"{subject} has legacy QA requirement {requirement_id} without "
                "an execution target; preserve that evidence and start a fresh "
                "deployment/plan execution, or use a sanctioned requirement "
                "retirement or supersession operation before rematerializing"
            )
        try:
            stored_target = json.loads(str(raw_target))
        except (TypeError, ValueError) as exc:
            raise QaPlanError(
                f"{subject} has invalid target evidence on QA requirement "
                f"{requirement_id}; preserve it and use sanctioned retirement "
                "or supersession before rematerializing"
            ) from exc
        if (
            not isinstance(stored_target, dict)
            or canonical_target(stored_target) != expected_json
            or stored_digest != expected_digest
            or target_digest(stored_target) != stored_digest
        ):
            raise QaPlanError(
                f"{subject} has QA requirement {requirement_id} bound to a "
                "different execution target; do not reuse it—start a fresh "
                "deployment/plan execution or use sanctioned retirement or "
                "supersession before rematerializing"
            )
        ids.append(requirement_id)
    return ids


def require_requirement_id_target(
    conn: Any,
    *,
    requirement_id: int,
    execution_target: Mapping[str, Any],
    subject: str,
) -> int:
    """Validate the winner of a concurrent idempotent insert."""
    marker = _placeholder(conn)
    row = query_one(
        conn,
        "SELECT id,execution_target_json,execution_target_digest "
        f"FROM qa_requirements WHERE id={marker}",
        (int(requirement_id),),
    )
    if row is None:
        raise QaPlanError(f"QA requirement {requirement_id} disappeared")
    return require_existing_target(
        [row],
        execution_target=execution_target,
        subject=subject,
    )[0]


def require_runnable_case(case: Any) -> dict:
    """Return the case config, refusing one its method could never run.

    Plan-case authoring validates the same contract, so this is the second
    reader of it — and the one that matters, because materialization is
    what mints the executable requirement. A row written around authoring
    would otherwise become a requirement whose only possible outcome is a
    runner refusing it at gate time.
    """
    from yoke_core.domain.qa_method_config_validation import (
        QaMethodConfigError,
        validate_method_config,
    )

    config = json.loads(str(case["method_config"] or "{}"))
    try:
        return validate_method_config(str(case["config_contract_id"]), config)
    except QaMethodConfigError as exc:
        raise QaPlanError(f"case {str(case['case_key'])!r}: {exc}") from exc


def insert_requirement(
    conn: Any,
    *,
    item_id: Optional[int] = None,
    deployment_run_id: Optional[str] = None,
    transition_id: Optional[str] = None,
    plan: Any,
    attachment: dict,
    case: Any,
    baseline: Optional[str],
    baseline_position: int,
    now: str,
    execution_target: dict[str, Any],
) -> Optional[int]:
    """Insert one immutable plan-case snapshot, returning its new id."""
    marker = _placeholder(conn)
    policy_id = case["success_policy_id"] or plan["success_policy_id"]
    params = (
        json.loads(str(case["success_policy_params"]))
        if case["success_policy_params"] is not None
        else json.loads(str(plan["success_policy_params"]))
    )
    require_case_target(
        {
            "instructions": case["instructions"],
            "expected_outcome": case["expected_outcome"],
            "method_config": require_runnable_case(case),
            "entry_surface": case["entry_surface"],
        },
        execution_target,
    )
    row = conn.execute(
        "INSERT INTO qa_requirements("
        "item_id, deployment_run_id, qa_kind, qa_phase, blocking_mode, "
        "requirement_source, success_policy, capability_requirements, "
        "plan_id, plan_case_key, case_position, baseline_position, "
        "method_id, method_name, runner_id, verdict_path, host_baseline, "
        "entry_surface, required_completion, "
        "workflow_transition_id, instructions, expected_outcome, "
        "method_config, execution_target_json, execution_target_digest, created_at"
        f") VALUES ({', '.join([marker] * 26)}) "
        "ON CONFLICT DO NOTHING RETURNING id",
        (
            item_id,
            deployment_run_id,
            "plan_case",
            str(attachment["qa_phase"]),
            "blocking",
            "flow_derived",
            _json({"id": policy_id, "params": params}),
            encoded_capability_kinds(
                case["required_capability_kinds"],
                subject=f"method {case['method_id']!r}",
            ),
            int(plan["id"]),
            str(case["case_key"]),
            int(case["position"]),
            int(baseline_position),
            str(case["method_id"]),
            str(case["method_name"]),
            str(case["runner_id"]),
            str(case["verdict_path"]),
            baseline,
            case["entry_surface"],
            case["required_completion"],
            transition_id,
            str(case["instructions"]),
            str(case["expected_outcome"]),
            str(case["method_config"]),
            canonical_target(execution_target),
            target_digest(execution_target),
            now,
        ),
    ).fetchone()
    if row is None:
        return None
    return int(row["id"] if isinstance(row, dict) else row[0])


def refresh_requirement(
    conn: Any,
    *,
    requirement_id: int,
    transition_id: str,
    plan: Any,
    attachment: dict,
    case: Any,
    baseline: Optional[str],
    baseline_position: int,
    execution_target: dict[str, Any],
) -> None:
    """Refresh a materialized case without severing its run history."""
    marker = _placeholder(conn)
    policy_id = case["success_policy_id"] or plan["success_policy_id"]
    params = (
        json.loads(str(case["success_policy_params"]))
        if case["success_policy_params"] is not None
        else json.loads(str(plan["success_policy_params"]))
    )
    require_case_target(
        {
            "instructions": case["instructions"],
            "expected_outcome": case["expected_outcome"],
            "method_config": require_runnable_case(case),
            "entry_surface": case["entry_surface"],
        },
        execution_target,
    )
    conn.execute(
        "UPDATE qa_requirements SET qa_kind='plan_case', "
        f"qa_phase={marker}, blocking_mode='blocking', "
        "requirement_source='flow_derived', "
        f"success_policy={marker}, capability_requirements={marker}, "
        f"plan_id={marker}, plan_case_key={marker}, case_position={marker}, "
        f"baseline_position={marker}, method_id={marker}, method_name={marker}, "
        f"runner_id={marker}, verdict_path={marker}, "
        f"host_baseline={marker}, entry_surface={marker}, "
        f"required_completion={marker}, workflow_transition_id={marker}, "
        f"instructions={marker}, expected_outcome={marker}, method_config={marker}, "
        f"execution_target_json={marker}, execution_target_digest={marker}, "
        "waived_at=NULL, waiver_rationale=NULL, waiver_source=NULL "
        f"WHERE id={marker}",
        (
            str(attachment["qa_phase"]),
            _json({"id": policy_id, "params": params}),
            encoded_capability_kinds(
                case["required_capability_kinds"],
                subject=f"method {case['method_id']!r}",
            ),
            int(plan["id"]),
            str(case["case_key"]),
            int(case["position"]),
            int(baseline_position),
            str(case["method_id"]),
            str(case["method_name"]),
            str(case["runner_id"]),
            str(case["verdict_path"]),
            baseline,
            case["entry_surface"],
            case["required_completion"],
            transition_id,
            str(case["instructions"]),
            str(case["expected_outcome"]),
            str(case["method_config"]),
            canonical_target(execution_target),
            target_digest(execution_target),
            int(requirement_id),
        ),
    )


def existing_requirement_id(
    conn: Any,
    *,
    item_id: Optional[int] = None,
    deployment_run_id: Optional[str] = None,
    plan_id: int,
    case_key: str,
    baseline: Optional[str],
    transition_id: Optional[str] = None,
) -> Optional[int]:
    """Resolve the snapshot that won a concurrent idempotent insert."""
    marker = _placeholder(conn)
    if (item_id is None) == (deployment_run_id is None):
        raise ValueError("exactly one of item_id or deployment_run_id is required")
    subject_column = "item_id" if item_id is not None else "deployment_run_id"
    subject_value: int | str = (
        int(item_id) if item_id is not None else str(deployment_run_id)
    )
    row = query_one(
        conn,
        "SELECT id FROM qa_requirements "
        f"WHERE {subject_column}={marker} AND plan_id={marker} "
        f"AND plan_case_key={marker} "
        f"AND COALESCE(host_baseline, '')={marker} "
        f"AND COALESCE(workflow_transition_id, '')={marker}",
        (
            subject_value,
            plan_id,
            case_key,
            baseline or "",
            transition_id or "",
        ),
    )
    return int(row["id"]) if row is not None else None


__all__ = [
    "existing_requirement_id",
    "insert_requirement",
    "refresh_requirement",
    "require_runnable_case",
    "require_existing_target",
    "require_requirement_id_target",
]
