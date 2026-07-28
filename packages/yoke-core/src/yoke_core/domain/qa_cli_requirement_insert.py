"""Storage shape for operator CLI QA requirement creation."""

from __future__ import annotations

from typing import Any


INSERT_SQL = """
    INSERT INTO qa_requirements
    (item_id, epic_id, task_num, deployment_run_id, qa_kind, qa_phase,
     target_env, blocking_mode, requirement_source, success_policy,
     capability_requirements, suite_id, workflow_transition_id, created_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
"""


def insert_params(
    *,
    item_id: int | None,
    epic_id: int | None,
    task_num: int | None,
    deployment_run_id: str | None,
    row: dict[str, Any],
    created_at: str,
) -> tuple[Any, ...]:
    """Return values in :data:`INSERT_SQL` column order."""
    return (
        item_id,
        epic_id,
        task_num,
        deployment_run_id,
        row["qa_kind"],
        row["qa_phase"],
        row.get("target_env"),
        row.get("blocking_mode", "blocking"),
        row.get("requirement_source", "explicit"),
        row.get("success_policy"),
        row.get("capability_requirements"),
        row.get("suite_id"),
        row.get("workflow_transition_id"),
        created_at,
    )


__all__ = ["INSERT_SQL", "insert_params"]
