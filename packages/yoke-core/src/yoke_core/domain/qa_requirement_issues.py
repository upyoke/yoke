"""Grade one selected QA attempt without rewriting its evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.qa_terminal_requirement_errors import _recovery_instruction


@dataclass(frozen=True)
class BlockingRequirementIssue:
    """Why one terminal blocking requirement is not merge-authorizing."""

    requirement_id: str
    state: str
    detail: str
    recovery: str


def issue_for_requirement(requirement: dict[str, Any]) -> BlockingRequirementIssue | None:
    requirement_id = str(requirement.get("id") or "<unknown>")
    if error := requirement.get("replacement_graph_error"):
        return BlockingRequirementIssue(
            requirement_id,
            "replacement-graph-invalid",
            error,
            "Reconcile the durable correction chain through registered correction surfaces",
        )
    if requirement.get("post_deploy_consumed"):
        return None
    review = requirement.get("human_review")
    if review:
        return BlockingRequirementIssue(
            requirement_id,
            "human-review",
            review["detail"],
            review["recovery"],
        )
    recovery = _recovery_instruction(requirement)
    if "post_deploy_consumed" in requirement:
        return BlockingRequirementIssue(
            requirement_id,
            "post-deploy-unaccepted",
            "the admitted source copies are not accepted on the completion run",
            recovery,
        )
    run_id = requirement.get("run_id")
    if run_id is None:
        return BlockingRequirementIssue(
            requirement_id,
            "missing",
            "no materialized run exists",
            recovery,
        )
    verdict = str(requirement.get("verdict") or "").strip().lower()
    completed_at = requirement.get("completed_at")
    if completed_at is not None:
        completed_at = parse_instant(completed_at)
    if verdict != "pass" or completed_at is None:
        actual = str(
            requirement.get("case_outcome")
            or requirement.get("execution_status")
            or verdict
            or "pending"
        ).strip()
        reason = str(requirement.get("verdict_reason") or "").strip()
        reason_text = f"; reason: {reason}" if verdict == "undetermined" else ""
        return BlockingRequirementIssue(
            requirement_id,
            "incomplete",
            f"latest run #{run_id} concluded {actual!r}{reason_text}, not completed success",
            recovery,
        )
    if requirement.get("current_passing_proof") is False:
        return BlockingRequirementIssue(
            requirement_id,
            "stale-proof",
            f"passing run #{run_id} does not prove the frozen configuration and target",
            recovery,
        )
    if issue := requirement.get("subject_proof_error"):
        return BlockingRequirementIssue(
            requirement_id, "subject-unproven", issue, recovery
        )
    return None
