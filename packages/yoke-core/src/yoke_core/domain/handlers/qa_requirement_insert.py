"""Storage shape shared by every dispatcher-created QA requirement.

One row, three attachment shapes. A case attaches to an item, or to a
deployment run as a whole, or to one stage — optionally one member item —
inside that run. The subject below carries whichever of those the caller
named, so the insert stays one statement rather than one per shape.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Optional


INSERT_SQL = (
    "INSERT INTO qa_requirements "
    "(item_id, epic_id, task_num, deployment_run_id, deployment_stage, "
    "deployment_member_item_id, qa_kind, qa_phase, "
    "target_env, execution_target_json, execution_target_digest, "
    "blocking_mode, requirement_source, success_policy, "
    "capability_requirements, suite_id, method_id, instructions, "
    "expected_outcome, method_config, workflow_transition_id, method_name, "
    "runner_id, verdict_path, created_at) "
    "VALUES ({p}, NULL, NULL, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, "
    "{p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) "
    "RETURNING id"
)


@dataclass(frozen=True)
class RequirementSubject:
    """Which subject one requirement row is attached to.

    Exactly one of ``item_id`` and ``deployment_run_id`` is set; the stage
    and member fields only ever accompany a run. The database enforces the
    same rule as a check constraint, so a subject built wrongly is refused
    by storage rather than stored as a row nothing can read back.
    """

    item_id: Optional[int] = None
    deployment_run_id: Optional[str] = None
    deployment_stage: Optional[str] = None
    deployment_member_item_id: Optional[int] = None

    @classmethod
    def for_item(cls, item_id: int) -> "RequirementSubject":
        return cls(item_id=int(item_id))


def insert_params(
    subject: RequirementSubject,
    row: dict[str, Any],
    now_iso: str,
) -> tuple[Any, ...]:
    """Return parameters in :data:`INSERT_SQL` column order."""
    return (
        subject.item_id,
        subject.deployment_run_id,
        subject.deployment_stage,
        subject.deployment_member_item_id,
        row["qa_kind"],
        row["qa_phase"],
        row.get("target_env"),
        row.get("execution_target_json"),
        row.get("execution_target_digest"),
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


__all__ = ["INSERT_SQL", "RequirementSubject", "insert_params"]
