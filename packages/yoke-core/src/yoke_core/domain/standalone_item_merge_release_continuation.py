"""The merge boundary's report to any release waiting on this merge.

Most merges have nothing waiting on them and this does nothing at all, which
is the point: a merge acquires no deployment behavior by landing. What it
does do is ask, once, whether a run was prepared against this item or against
work this item was coordinated with, and if so, whether this merge is the one
that completes the set.

It runs after evidence is recorded and before the terminal transition. The
order matters in both directions. The bound lineage is read from the merge
evidence, so it has to exist first; and the delivery gate that holds an item
open until its run has succeeded reads the run this step binds, so binding
after the transition would gate on a run that was still nameless when the
gate looked.

A failure here never fails the merge. The branch is already on the base
branch by this point, and turning a landed merge into an error over a release
hand-off would send an operator to repair a merge that is fine. The outcome
is reported as a warning and the same command re-run finishes the job, since
continuation re-derives everything it needs from durable rows.
"""

from __future__ import annotations

from typing import Any

from yoke_core.engines.runs_continue_for_item import (
    OUTCOME_BOUND,
    OUTCOME_NONE,
    OUTCOME_WAITING,
    continue_for_item,
)


def continue_prepared_release(
    *,
    item_id: int,
    session_id: str = "",
) -> tuple[dict[str, Any] | None, str]:
    """Advance a prepared release this merge may complete.

    Returns ``(envelope_fragment, warning)``. Both are empty when no prepared
    run is waiting on this item, which is the ordinary case.
    """
    try:
        outcome = continue_for_item(item_id, session_id=session_id or None)
    except Exception as exc:
        return None, (
            f"prepared release continuation could not be evaluated: {exc}. "
            "The merge is complete; re-run this command, or check with "
            f"`yoke deployment-runs find-by-item {item_id} --status created`"
        )
    if outcome.outcome == OUTCOME_NONE:
        return None, ""
    if not outcome.ok:
        return None, f"prepared release not advanced: {outcome.error}"
    fragment: dict[str, Any] = {
        "run_id": outcome.run_id,
        "outcome": outcome.outcome,
    }
    if outcome.outcome == OUTCOME_WAITING:
        fragment["waiting_on"] = list(outcome.waiting_on)
        return fragment, ""
    if outcome.outcome == OUTCOME_BOUND:
        fragment["release_lineage"] = outcome.release_lineage
        fragment["handed_off_to"] = outcome.handed_off_to
        if not outcome.message_id:
            return fragment, (
                f"prepared run {outcome.run_id} now names "
                f"{outcome.release_lineage} but the hand-off to the deploy "
                "authority was not delivered; re-run this command, or tell "
                f"the holder to run `yoke deployment-runs get {outcome.run_id}`"
            )
        fragment["message_id"] = outcome.message_id
    return fragment, ""


__all__ = ["continue_prepared_release"]
