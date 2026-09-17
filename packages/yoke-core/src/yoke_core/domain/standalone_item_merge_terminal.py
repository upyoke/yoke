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


def _execute(
    item_id: int,
    source_status: str,
    target_status: str,
    *,
    done_nonce_verified: bool = False,
) -> str:
    response = call_dispatcher(
        function_id="lifecycle.transition.execute",
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "source_status": source_status,
            "target_status": target_status,
            "reason": TRANSITION_REASON,
            "done_nonce_verified": done_nonce_verified,
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
    stages: tuple[str, ...] = (TERMINAL_STATUS,),
    delivery_discharged: bool = False,
) -> tuple[str, str]:
    """Close the item out, or land it at its pinned release wait.

    ``stages`` is the caller's own resolution, from the pinned definition
    and the item's registered deployment flow, of the declared stages this
    close-out walks -- one transition per declared edge, so a stage between
    here and the terminal one still runs its own gates rather than being
    skipped by a jump the definition never declared. Deciding the whole
    route before calling means each attempt lands at a target that is
    actually declared, rather than trying ``done`` and reinterpreting any
    refusal (an approval gate, a transport failure, a stale precondition)
    as license to try a different one.

    ``delivery_discharged`` says the merge that just landed was the whole
    of this item's delivery, so this boundary asserts the done-transition
    ceremony on its terminal step the same way the deploy engine asserts it
    after running one. An item whose delivery is still owed is never marked
    discharged, and its ``stages`` stop at the release wait.

    Returns ``(new_status, refusal)``. ``new_status`` is the item's actual
    resulting status -- the last attempted target on success -- and is only
    meaningful when ``refusal`` is empty.
    """
    if source_status == TERMINAL_STATUS:
        return TERMINAL_STATUS, ""
    # Either identity proves the landing: a queue or squash merge can rewrite
    # the lane head, leaving only the merge commit reachable from the target.
    # Empty identities skip that git read only when persisted evidence attests
    # the no-change floor; missing SHAs alone are corrupt landing evidence.
    identities = tuple(
        sha for sha in (lane.commit_sha, lane.merge_sha) if sha
    )
    unlanded = (
        f"terminal transition refused: recorded merge commit "
        f"{lane.commit_sha} is not reachable from {lane.target!r}"
    )
    if not identities:
        if not evidence.attested_empty_landing(item_id):
            return "", unlanded
    elif not any(
        git.is_landed(repo_root, sha, lane.target) for sha in identities
    ):
        return "", unlanded
    if recovery.claim_error(item_id, session_id):
        _recovered, recovery_error = recovery.reacquire_landed_claim(
            item_id=item_id, session_id=session_id, lane=lane,
        )
        if recovery_error:
            if evidence.authoritative_status_is(item_id, TERMINAL_STATUS):
                return TERMINAL_STATUS, ""
            return "", (
                f"the merge is landed but close-out authority could not be "
                f"recovered to finish it: {recovery_error}"
            )
    reached = source_status
    for target in stages:
        refusal = _execute(
            item_id,
            reached,
            target,
            done_nonce_verified=delivery_discharged and target == TERMINAL_STATUS,
        )
        if refusal:
            return "", refusal
        reached = target
    return reached, ""


__all__ = ["TERMINAL_STATUS", "TRANSITION_REASON", "transition_to_done"]
