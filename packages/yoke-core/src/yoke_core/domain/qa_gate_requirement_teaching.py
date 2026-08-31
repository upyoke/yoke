"""Remediation text for missing transition-bound QA requirements."""

from __future__ import annotations

from yoke_core.domain.project_identity_item_ref import item_ref_for_id
from yoke_core.domain.qa_gate_definitions import GateTarget


QA_REQUIREMENTS_EMPTY = "GATE_QA_REQUIREMENTS_EMPTY"


def missing_verification_requirement_errors(
    *,
    target: GateTarget,
    target_name: str,
    transition_id: str,
    target_transition: str = "reviewing-implementation",
) -> list[str]:
    """Build the supported creation recipe for the gate target shape."""
    errors = [
        f"{QA_REQUIREMENTS_EMPTY}: Cannot transition "
        f"{target_name} to '{target_transition}' -- "
        "no qa_requirements found.",
        f"  Add at least one QA requirement before moving to {target_transition}:",
        "  Raise the project to executed tests: yoke qa registered-command set "
        '--project <project> --scope quick --command "<argv>"',
    ]
    if target.item_id is not None:
        errors.append(
            f"  yoke qa requirement add --item {item_ref_for_id(int(target.item_id))} "
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


__all__ = ["QA_REQUIREMENTS_EMPTY", "missing_verification_requirement_errors"]
