"""Validated QA plan case storage."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.qa_case_starting_state import (
    StartingStateError,
    chain_baselines,
    normalize_starting_state,
)
from yoke_core.domain.qa_converging_columns import converged_values, present_columns
from yoke_core.domain.qa_plan_management import QaPlanError, _json, _placeholder


def apply_starting_states(
    cases: list[dict[str, Any]],
    *,
    runner_ids: Mapping[str, str],
) -> None:
    """Refuse an undeclared or impossible starting state; normalize the rest.

    ``cases`` are validated and position-ordered; ``runner_ids`` maps each
    case's method to the runner that decides whether it is machine-run.
    """
    try:
        chain_baselines(
            [{**case, "runner_id": runner_ids[case["method_id"]]} for case in cases]
        )
        for case in cases:
            case["starting_state"], case["starting_state_reason"] = (
                normalize_starting_state(
                    case_key=case["case_key"],
                    runner_id=runner_ids[case["method_id"]],
                    host_baselines=case["host_baselines"],
                    starting_state=case.get("starting_state"),
                    starting_state_reason=case.get("starting_state_reason"),
                )
            )
    except StartingStateError as exc:
        raise QaPlanError(str(exc)) from exc


def insert_plan_cases(
    conn: Any,
    *,
    plan_id: int,
    cases: list[dict[str, Any]],
    stamp: str,
) -> None:
    """Replace a plan's stored cases with validated ones."""
    marker = _placeholder(conn)
    target_column_present = "target_envs" in present_columns(conn, "qa_plan_cases")
    if not target_column_present and any(case["target_envs"] for case in cases):
        raise QaPlanError(
            "qa_case_environment_schema_unavailable: install the release declaring "
            "qa_plan_cases.target_envs and let boot converge it, then retry "
            "`yoke qa plan-cases replace`"
        )
    conn.execute(f"DELETE FROM qa_plan_cases WHERE plan_id={marker}", (plan_id,))
    for case in cases:
        values = converged_values(
            conn,
            "qa_plan_cases",
            {
                "plan_id": plan_id,
                "case_key": case["case_key"],
                "position": case["position"],
                "method_id": case["method_id"],
                "instructions": case["instructions"],
                "expected_outcome": case["expected_outcome"],
                "method_config": _json(case.get("method_config") or {}),
                "success_policy_id": case.get("success_policy_id"),
                "success_policy_params": _json(case["success_policy_params"])
                if case.get("success_policy_params") is not None
                else None,
                "host_baselines": _json(case["host_baselines"]),
                **({"target_envs": _json(case["target_envs"])} if target_column_present else {}),
                "starting_state": case.get("starting_state"),
                "starting_state_reason": case.get("starting_state_reason"),
                "entry_surface": case.get("entry_surface"),
                "required_completion": case.get("required_completion"),
                "created_at": stamp,
                "updated_at": stamp,
            },
        )
        conn.execute(
            f"INSERT INTO qa_plan_cases({', '.join(values)}) "
            f"VALUES ({', '.join([marker] * len(values))})",
            tuple(values.values()),
