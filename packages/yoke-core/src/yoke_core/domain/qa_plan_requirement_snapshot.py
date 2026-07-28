"""Idempotent QA requirement writes for materialized plan cases."""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_plan_management import _json, _placeholder


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
) -> Optional[int]:
    """Insert one immutable plan-case snapshot, returning its new id."""
    marker = _placeholder(conn)
    policy_id = case["success_policy_id"] or plan["success_policy_id"]
    params = (
        json.loads(str(case["success_policy_params"]))
        if case["success_policy_params"] is not None
        else json.loads(str(plan["success_policy_params"]))
    )
    row = conn.execute(
        "INSERT INTO qa_requirements("
        "item_id, deployment_run_id, qa_kind, qa_phase, blocking_mode, "
        "requirement_source, success_policy, capability_requirements, "
        "plan_id, plan_case_key, case_position, baseline_position, "
        "method_id, method_name, executor_id, required_capability_kind, "
        "verdict_path, host_baseline, entry_surface, required_completion, "
        "workflow_transition_id, instructions, expected_outcome, "
        "method_config, created_at"
        f") VALUES ({', '.join([marker] * 25)}) "
        "ON CONFLICT DO NOTHING RETURNING id",
        (
            item_id,
            deployment_run_id,
            "plan_case",
            str(attachment["qa_phase"]),
            "blocking",
            "flow_derived",
            _json({"id": policy_id, "params": params}),
            _json([case["required_capability_kind"]])
            if case["required_capability_kind"]
            else _json([]),
            int(plan["id"]),
            str(case["case_key"]),
            int(case["position"]),
            int(baseline_position),
            str(case["method_id"]),
            str(case["method_name"]),
            str(case["executor_id"]),
            case["required_capability_kind"],
            str(case["verdict_path"]),
            baseline,
            case["entry_surface"],
            case["required_completion"],
            transition_id,
            str(case["instructions"]),
            str(case["expected_outcome"]),
            str(case["method_config"]),
            now,
        ),
    ).fetchone()
    if row is None:
        return None
    return int(row["id"] if isinstance(row, dict) else row[0])


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


__all__ = ["existing_requirement_id", "insert_requirement"]
