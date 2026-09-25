"""Release-wait classification and teaching for a merged item.

A merge at the pinned release wait retains its work claim until delivery
and post-deploy validation complete. The same active-work-claim rule protects
this holder and every other work claimant through idle sweeps and restarts.
Parking records the pending delivery for wake and recovery routing.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_runtime import workflow_runtime_from_row

TOUCH_FUNCTION = "sessions.touch"
HOLDER_FUNCTION = "claims.work.holder_get"


RELEASE_WAIT_RETENTION_TEACHING = (
    "A merge that lands your item at its pinned release wait is a completed "
    "merge that is NOT a finished item: the delivery still has to run and "
    "its post-deploy validation still has to be walked before the item "
    "reaches done. That close-out therefore keeps your work claim and parks "
    "your session with the wait named, and you keep both. Do NOT release the "
    "claim and do NOT end your session there — report what landed in your "
    "own output, say you are waiting on delivery, and stop deliberately. A "
    "deployment wake re-enters you when a QA stage needs you or your own "
    "item-scoped QA is accepted. A recorded `post_deploy_no_obligation`, or "
    "a member whose scoped post-deploy QA all passed or was waived, closes "
    "automatically when the completion-flow run succeeds. A final member "
    "whose selected flow has no run QA closes when its own final production "
    "QA is accepted, even while sibling QA holds the run open. A flow with "
    "required run QA holds every member until that QA and run success. "
    "These close-outs need no extra wake and end an otherwise empty holder "
    "session. A stage that "
    "wants your evidence is run by naming that stage "
    "AND your item, because a stage credits only requirements bound to its "
    "own name: `yoke watch qa-plan -- --deployment-run-id RUN --stage STAGE "
    "--member <ITEM> --project P` (that wrapper, not "
    "`yoke watch qa-case`, which wraps the narrower requirement-id form). "
    "Add `--plan PLAN` only when the wake says the stage names no cases: a "
    "stage that already names its own refuses --plan, because a plan there "
    "materializes a second, duplicate set of obligations beside the ones it "
    "credits. The wake prints the exact recipe for its own stage. "
    "The run-wide form and `yoke qa case run` do not credit it. After the "
    "item-scoped stage is accepted, check whether the item reached done; "
    "otherwise re-park while its completion flow finishes. Do not re-run "
    "merge solely for that acceptance. A delivery "
    "wake is reserved for a cleared member the automatic close-out could "
    "not finish, and names the required recovery. Only once the item "
    "reaches done do you send the DONE report and end. Any prompt that wakes "
    "you CLEARS that park, including one that turns out not to finish the "
    "item, so whenever you go quiet still short of done — a wake you handled, "
    "a close-out that refused, a message about something else — re-park "
    'before stopping: `yoke sessions touch --mode parked --reason "awaiting '
    '<ITEM> delivery"`. The active work claim protects the session; '
    "parking records its delivery wait for wake and recovery routing."
)


def park_reason(public_ref: str) -> str:
    """The concrete deployment wait a parked release-wait owner declares."""
    named = (public_ref or "").strip() or "this item"
    return (
        f"awaiting {named} delivery: deployment run, then post-deploy "
        f"validation and the done close-out"
    )


def item_at_release_wait(row: Any, status: str) -> bool:
    """Whether a joined item/workflow-version row stands at its pinned wait.

    An unreadable pin answers no. A definition this cannot interpret is not
    evidence that an item is waiting, and every caller here treats "waiting"
    as a reason to hold something open or to announce something — both worse
    to get wrong than a missed spare.
    """
    try:
        release_stage = delivery_redirect_stage(workflow_runtime_from_row(row))
    except Exception:  # noqa: BLE001 - an unreadable pin names no wait
        return False
    return release_stage is not None and str(status or "") == release_stage


__all__ = [
    "HOLDER_FUNCTION",
    "RELEASE_WAIT_RETENTION_TEACHING",
    "TOUCH_FUNCTION",
    "item_at_release_wait",
    "park_reason",
]
