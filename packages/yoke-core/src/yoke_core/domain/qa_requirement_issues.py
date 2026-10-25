"""Grade one selected QA attempt without rewriting its evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.qa_terminal_requirement_errors import _recovery_instruction


@dataclass(frozen=True)
class BlockingRequirementIssue:
    """Why one terminal blocking requirement is not merge-authorizing."""

    requirement_id: str
    state: str
    detail: str
    recovery: str



def _render_shas(shas: Sequence[str]) -> str:
    return ", ".join(sha for sha in shas) if shas else "<missing>"


def issue_for_requirement(
    requirement: dict[str, Any],
    *,
    accepted_shas: Sequence[str],
    contains_commit: Callable[[str, str], bool] | None = None,
) -> BlockingRequirementIssue | None:
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
    run_sha = str(requirement.get("recorded_head_sha") or "").strip()
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
    # Deployment proof retains its release binding, independently of lane QA.
    if (
        requirement.get("deployment_run_id")
        or requirement.get("qa_phase") == "post_deploy"
    ):
        return None
    try:
        if run_sha and any(
            run_sha == head or (contains_commit and contains_commit(head, run_sha))
            for head in accepted_shas
        ):
            return None
    except ValueError as exc:
        return BlockingRequirementIssue(
            requirement_id, "lane-history-unavailable", str(exc), recovery
        )
    from yoke_contracts.refusal_recovery import compose_refusal

    return BlockingRequirementIssue(
        requirement_id,
        "outside-lane",
        compose_refusal(
            f"passing run #{run_id} recorded SHA {run_sha or '<missing>'}; "
            f"it is not proven in the item's lane history ending at {_render_shas(accepted_shas)}",
            recovery="run the requirement from this item's claimed lane and record its start commit",
        ),
        recovery,
    )

