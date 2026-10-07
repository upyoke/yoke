"""Stored QA plan cases: their starting-state declaration and their rows."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.qa_case_starting_state import (
    StartingStateError,
    chain_baselines,
    normalize_starting_state,
)
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
    conn.execute(f"DELETE FROM qa_plan_cases WHERE plan_id={marker}", (plan_id,))
    for case in cases:
        conn.execute(
            "INSERT INTO qa_plan_cases("
            "plan_id, case_key, position, method_id, instructions, "
            "expected_outcome, method_config, success_policy_id, "
            "success_policy_params, host_baselines, starting_state, "
            "starting_state_reason, entry_surface, required_completion, "
            "created_at, updated_at"
            f") VALUES ({', '.join([marker] * 16)})",
            (
                plan_id,
                case["case_key"],
                case["position"],
                case["method_id"],
                case["instructions"],
                case["expected_outcome"],
                _json(case.get("method_config") or {}),
                case.get("success_policy_id"),
                _json(case["success_policy_params"])
                if case.get("success_policy_params") is not None
                else None,
                _json(case["host_baselines"]),
                case.get("starting_state"),
                case.get("starting_state_reason"),
                case.get("entry_surface"),
                case.get("required_completion"),
                stamp,
                stamp,
            ),
        )


__all__ = ["apply_starting_states", "insert_plan_cases"]
