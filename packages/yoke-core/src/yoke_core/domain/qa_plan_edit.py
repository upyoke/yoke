"""Compare-and-swap editing for project-scoped QA plans."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_converging_columns import (
    STARTING_STATE_COLUMNS,
    converged_select,
)
from yoke_core.domain.qa_plan_case_store import insert_plan_cases
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    _json,
    _next_updated_at,
    _placeholder,
    _project_id,
    _validate_target_environment,
    _validated_plan_cases,
)


class QaPlanConflictError(RuntimeError):
    """The plan changed after the caller read its authoring document."""


def _decode(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return fallback


def _case_document(row: Any) -> dict[str, Any]:
    return {
        "case_key": str(row["case_key"]),
        "position": int(row["position"]),
        "method_id": str(row["method_id"]),
        "instructions": str(row["instructions"]),
        "expected_outcome": str(row["expected_outcome"]),
        "method_config": _decode(row["method_config"], {}),
        "success_policy_id": row["success_policy_id"],
        "success_policy_params": _decode(
            row["success_policy_params"],
            None,
        ),
        "host_baselines": _decode(row["host_baselines"], []),
        "starting_state": row["starting_state"],
        "starting_state_reason": row["starting_state_reason"],
        "target_envs": _decode(row["target_envs"], []),
        "entry_surface": row["entry_surface"],
        "required_completion": row["required_completion"],
    }


def _current_cases(conn: Any, plan_id: int) -> list[dict[str, Any]]:
    marker = _placeholder(conn)
    return [
        _case_document(row)
        for row in query_rows(
            conn,
            "SELECT case_key, position, method_id, instructions, "
            "expected_outcome, method_config, success_policy_id, "
            "success_policy_params, host_baselines, "
            f"{converged_select(conn, 'qa_plan_cases', (*STARTING_STATE_COLUMNS, 'target_envs'))}, "
            "entry_surface, "
