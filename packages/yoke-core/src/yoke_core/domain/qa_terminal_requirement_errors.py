"""Recovery text for terminal QA requirements lacking current proof."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoke_core.domain.qa_terminal_settlement import BlockingRequirementIssue


def requirement_issue_errors(
    issues: list[BlockingRequirementIssue],
    *,
    public_ref: str,
    target_status: str,
) -> list[str]:
    """Render actionable missing, incomplete, and stale-SHA refusals."""
    if not issues:
        return []
    errors = [
        f"Error: Cannot transition {public_ref} to {target_status!r} -- "
        f"{len(issues)} blocking QA requirement(s) lack a completed verdict "
        "for the merging commit.",
        "  A waiver is an explicit, recorded, requirement-scoped operator "
        "override; it is not part of the normal merge recipe.",
    ]
    errors.extend(
        f"  - Requirement #{issue.requirement_id} [{issue.state}]: "
        f"{issue.detail}. {issue.recovery}."
        for issue in issues
    )
    return errors


def _recovery_instruction(requirement: dict[str, Any]) -> str:
    requirement_id = str(requirement.get("id") or "<unknown>")
    case_command = f"yoke qa case run --requirement-id {requirement_id}"
    method_id = str(requirement.get("method_id") or "")
    if not method_id:
        qa_kind = str(requirement.get("qa_kind") or "ac_verification")
        return (
            f"Record the exact-head evidence with `yoke qa run add --requirement-id "
            f"{requirement_id} --performed-by agent --qa-kind {qa_kind} "
            "--verdict pass --head-sha <full-commit-sha> --raw-result "
            "'<evidence and result>'`"
        )
    if requirement.get("qa_phase") == "post_deploy":
        return (
            "Finish the admitted post-deploy QA through `yoke watch qa-plan -- "
            "--item ITEM --stage STAGE --project P`; "
            "the selected completion run must accept this source's copies "
            "at its recorded candidate and target before done can settle"
        )
    return f"Run `{case_command}`"
