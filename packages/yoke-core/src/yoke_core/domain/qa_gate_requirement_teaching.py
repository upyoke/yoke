"""Remediation text for missing transition-bound QA requirements."""

from __future__ import annotations

from yoke_core.domain.qa_gate_definitions import GateTarget


def missing_verification_requirement_errors(
    *,
    target: GateTarget,
    target_name: str,
    transition_id: str,
) -> list[str]:
    """Build the supported creation recipe for the gate target shape."""
    errors = [
        "Error: Cannot transition "
        f"{target_name} to 'reviewing-implementation' -- "
        "no qa_requirements found.",
        "  Add at least one QA requirement before moving to reviewing-implementation:",
    ]
    if target.item_id is not None:
        errors.append(
            f"  yoke qa requirement add --item YOK-{target.item_id} "
            "--qa-kind implementation_review --qa-phase verification "
            f"--workflow-transition {transition_id}"
        )
        return errors

    # Epic-task attachment has no typed adapter because the registered
    # item-claim-gated surface accepts item attachments only.
    errors.append(
        "  python3 -m yoke_core.domain.qa requirement-add "
        f"--epic-id {target.epic_id} --task-num {target.task_num} "
        "--qa-kind implementation_review --qa-phase verification "
        f"--workflow-transition {transition_id}"
    )
    return errors


__all__ = ["missing_verification_requirement_errors"]
