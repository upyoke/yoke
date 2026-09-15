"""Has an item's live status reached its pinned release wait.

Split out of :mod:`standalone_item_merge_cli` to stay under the authored
file line budget; used only there, to decide whether a mismatched branch
head at the merge boundary is foreign/stale work or this same item's own
next legitimate merge attempt after genuinely returning short of release.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.merge_review_readiness import pinned_workflow_for_item
from yoke_core.domain.workflow_behavior import delivery_redirect_stage


def reached_release(item: dict[str, Any], status: str) -> bool:
    """``True`` (the safe default) on a workflow with no release-stage
    concept, or on a definition read that fails -- both keep
    ``stale_unlanded_work``'s existing foreign/stale-work refusal exactly
    as it already behaves. Only a workflow that both owns a release wait
    AND whose item has genuinely returned short of it (a fix in progress
    after a failed release-stage verdict) answers ``False``.
    """
    workflow, error = pinned_workflow_for_item(item)
    if workflow is None or error:
        return True
    release_stage_id = delivery_redirect_stage(workflow)
    if release_stage_id is None:
        return True
    return workflow.has_reached_stage(status, release_stage_id)


__all__ = ["reached_release"]
