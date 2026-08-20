"""Storage shape shared by single and batched QA requirement creation."""

from __future__ import annotations

import json
from typing import Any


INSERT_SQL = (
    "INSERT INTO qa_requirements "
    "(item_id, epic_id, task_num, deployment_run_id, qa_kind, qa_phase, "
    "target_env, blocking_mode, requirement_source, success_policy, "
    "capability_requirements, suite_id, method_id, instructions, "
    "expected_outcome, method_config, workflow_transition_id, method_name, "
    "runner_id, verdict_path, created_at) "
    "VALUES ({p}, NULL, NULL, NULL, {p}, {p}, {p}, {p}, {p}, {p}, "
    "{p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) "
    "RETURNING id"
)


def insert_params(
    item_id: int,
    row: dict[str, Any],
    now_iso: str,
) -> tuple[Any, ...]:
    """Return parameters in :data:`INSERT_SQL` column order."""
    return (
        int(item_id),
        row["qa_kind"],
        row["qa_phase"],
        row.get("target_env"),
        str(row.get("blocking_mode") or "blocking"),
        str(row.get("requirement_source") or "explicit"),
        row.get("success_policy"),
        row.get("capability_requirements"),
        row.get("suite_id"),
        row.get("method_id"),
        row.get("instructions"),
        row.get("expected_outcome"),
        (
            json.dumps(row["method_config"], sort_keys=True)
            if row.get("method_id")
            else None
        ),
        row.get("workflow_transition_id"),
        row.get("method_name"),
        row.get("runner_id"),
        row.get("verdict_path"),
        now_iso,
    )


__all__ = ["INSERT_SQL", "insert_params"]
