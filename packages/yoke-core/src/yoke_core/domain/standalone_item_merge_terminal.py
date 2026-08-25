"""The terminal transition a landed standalone merge still owes.

When close-out is re-entered after a crash, the transition is often the only
step left, and the thing that most commonly stops it there is not a
disagreement about whether the work landed. The claim can be gone — released
by the close-out that crashed, or by the stale-session sweep while a queue
landing was polled for forty minutes — so the authority is restored *before*
the transition is attempted, from the same landing proof the merge boundary
already verified, rather than refusing over a lock that was only ever a guard
on unlanded work.

Restoring it beforehand is what keeps the refusal path honest. The transition
itself is dispatched once and its answer is reported verbatim: the transport
owns retries and replays a request that did land, so re-reading the item to
ask whether a refusal secretly succeeded would be a local patch over a relay
that already handles it.

The one reading that remains is for the race the recovery cannot take: an
item another closer has already moved to ``done`` refuses the replacement
claim because it is terminal, and a landed, closed-out merge reported as
failed sends an operator to repair state that is already correct.

What stays fail-closed is the landing itself: a merge identity the base branch
does not contain is refused here exactly as before, because that is the one
check the terminal status depends on being true.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import standalone_item_merge_evidence as evidence
from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain import standalone_item_merge_recovery as recovery
from yoke_core.domain.standalone_item_merge_landed import LandedLane

TERMINAL_STATUS = evidence.CLOSED_OUT_STATUS
TRANSITION_REASON = "Merged and evidence recorded"


def _relay_error(response: Any, fallback: str) -> str:
    error = getattr(response, "error", None)
    return getattr(error, "message", None) or fallback if error else fallback


def _execute(item_id: int, source_status: str) -> str:
    response = call_dispatcher(
        function_id="lifecycle.transition.execute",
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "source_status": source_status,
            "target_status": TERMINAL_STATUS,
            "reason": TRANSITION_REASON,
        },
    )
    if response.success:
        return ""
    return _relay_error(response, "terminal transition refused")


def transition_to_done(
    *,
    item_id: int,
    source_status: str,
    repo_root: str,
    lane: LandedLane,
    session_id: str = "",
) -> str:
    """Close the item out. Returns the refusal, or empty on success."""
    if source_status == TERMINAL_STATUS:
        return ""
    # Either identity proves the landing: a queue or squash merge can rewrite
    # the lane head, leaving only the merge commit reachable from the target.
    landed = any(
        git.is_landed(repo_root, sha, lane.target)
        for sha in (lane.commit_sha, lane.merge_sha)
        if sha
    )
    if not landed:
        return (
            f"terminal transition refused: recorded merge commit "
            f"{lane.commit_sha} is not reachable from {lane.target!r}"
        )
    if recovery.claim_error(item_id, session_id):
        _recovered, recovery_error = recovery.reacquire_landed_claim(
            item_id=item_id, session_id=session_id, lane=lane,
        )
        if recovery_error:
            if evidence.authoritative_status_is(item_id, TERMINAL_STATUS):
                return ""
            return (
                f"the merge is landed but close-out authority could not be "
                f"recovered to finish it: {recovery_error}"
            )
    return _execute(item_id, source_status)


__all__ = ["TERMINAL_STATUS", "TRANSITION_REASON", "transition_to_done"]
