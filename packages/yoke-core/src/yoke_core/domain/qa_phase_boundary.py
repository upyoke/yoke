"""Which QA phase belongs before merge versus after deployment.

Lifecycle gates and merge admission share this split so a ``post_deploy``
row cannot be mistaken for pre-release proof, and a ``verification`` row
cannot be mistaken for completion-only acceptance. The phase column is the
declared binding; URL, environment name, and instruction prose are not.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_runtime import WorkflowRuntime


PRE_MERGE_QA_PHASE = "verification"
POST_MERGE_QA_PHASES = frozenset({"post_deploy", "manual_acceptance"})
TERMINAL_DONE = "done"


def applies_at_pre_merge(requirement: Mapping[str, Any]) -> bool:
    """Whether this row is in the set merge admission evaluates.

    A missing phase stays fail-closed with pre-merge verification so older
    payloads that omit the column keep their current merge-boundary force.
    """
    phase = str(requirement.get("qa_phase") or PRE_MERGE_QA_PHASE).strip()
    return phase == PRE_MERGE_QA_PHASE


def is_pre_release_stage(workflow: WorkflowRuntime, transition: str) -> bool:
    """True when ``transition`` is before the pin's delivery wait, if any."""
    release_wait = delivery_redirect_stage(workflow)
    position = workflow.stage_index(transition)
    if position is None:
        return False
    if release_wait is None:
        return transition not in workflow.terminal_stage_ids
    release_at = workflow.stage_index(release_wait)
    if release_at is None:
        return transition not in workflow.terminal_stage_ids
    return position < release_at


def post_merge_binding_refusal(
    workflow: WorkflowRuntime,
    *,
    transition: str,
    qa_phase: str,
) -> Optional[str]:
    """Why a post-merge phase cannot bind here, with the supported recovery."""
    phase = str(qa_phase or "").strip()
    if phase not in POST_MERGE_QA_PHASES:
        return None
    if not is_pre_release_stage(workflow, transition):
        return None
    release_wait = delivery_redirect_stage(workflow)
    attach_at = release_wait or TERMINAL_DONE
    return (
        f"qa_phase {phase!r} is post-deployment acceptance and cannot bind to "
        f"pre-release stage {transition!r} on "
        f"{workflow.workflow_id}@{workflow.version}. Attach it at "
        f"{attach_at!r}: yoke qa requirement add --item PREFIX-N "
        f"--qa-phase {phase} --workflow-transition {attach_at} ... "
        "(or attach the case to the deployment run: yoke qa requirement add "
        "--deployment-run RUN-ID --qa-phase post_deploy ...). A row already "
        "recorded against a pre-release stage rebinds in place rather than "
        "being replaced: yoke qa requirement update --requirement-id N "
        f"--field workflow_transition_id --value {attach_at}. Existing "
        "verification-phase checks against a live production environment stay "
        "on the review transition."
    )


__all__ = [
    "POST_MERGE_QA_PHASES",
    "PRE_MERGE_QA_PHASE",
    "TERMINAL_DONE",
    "applies_at_pre_merge",
    "is_pre_release_stage",
    "post_merge_binding_refusal",
]
