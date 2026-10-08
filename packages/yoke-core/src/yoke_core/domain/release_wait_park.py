"""Park the merging session on the delivery wait its own close-out reached.

:mod:`release_wait_ownership` says what a release-wait owner IS; this is the
one write that makes the merge boundary produce one. It runs inside
``yoke merge item``, which is installed-client code reaching the control
plane by relay, so every write here goes through the function dispatcher and
this module never opens a control-plane database.

The park is stamped rather than taught because a retention that depends on
an agent remembering a paragraph is exactly the retention that was already
being lost: twelve items reached their release wait with the claim released
or the session ended, against four that parked and held. Stamping it means
the worker's own quiet is a declared wait the sweep can read, whatever the
worker does next.

Nothing here can fail the merge. By the time it runs the branch is on the
base branch and the item is at its release wait, so every failure is
reported inside the envelope's ``release_wait`` block and the outcome the
caller prints still carries the retention teaching.
"""

from __future__ import annotations

from yoke_core.domain.public_item_target import public_item_target

from collections.abc import Mapping
from typing import Any

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import (
    build_actor,
    call_dispatcher,
)
from yoke_core.domain.close_out_control_plane_authority import (
    connected_control_plane,
)
from yoke_core.domain.release_wait_ownership import (
    HOLDER_FUNCTION,
    TOUCH_FUNCTION,
    park_reason,
)
from yoke_core.domain.merge_review_readiness import pinned_workflow_for_item
from yoke_core.domain.release_wait_facts import (
    OWES_NOTHING,
    OWES_QA,
    OWES_UNREAD,
    delivery_obligation,
    session_wake,
    stage_recipe,
)
from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id
from yoke_core.domain.session_mode import SESSION_MODE_PARKED
from yoke_core.domain.workflow_behavior import delivery_redirect_stage


def at_release_wait(item: dict[str, Any], status: str) -> bool:
    """Whether this merge-boundary item dict stands at its pinned wait.

    Reads the item's own pinned definition, so a workflow with no release
    wait and one this cannot interpret both answer no. Deliberately narrower
    than ``reached_release``, whose safe default is yes: that answer belongs
    to a refusal, and this one decides whether to hold a claim open.
    """
    workflow, error = pinned_workflow_for_item(item)
    if workflow is None or error:
        return False
    try:
        return delivery_redirect_stage(workflow) == str(status or "")
    except ValueError:
        return False


def retain_if_waiting(
    envelope: dict[str, Any],
    *,
    item: dict[str, Any],
    item_id: int,
    public_ref: str,
    status: str,
    session_id: str,
) -> None:
    """Re-stamp the park on a close-out that left the item at its wait.

    Every way this merge can decline — an unresolvable delivery clearance, a
    refused terminal transition — leaves a session that was parked on the
    wait, woke to run the close-out, and had its park cleared by the very
    prompt that delivered the wake. Without this the owner ends the attempt
    unparked and reclaimable, which is the abandonment the retention exists
    to prevent: the refusal path has to put the park back.
    """
    if not at_release_wait(item, status):
        return
    retain_for_delivery(
        envelope,
        item=item,
        item_id=item_id,
        public_ref=public_ref,
        session_id=session_id,
    )


def _held_by(dispatch: Any, item_id: int, session_id: str) -> bool:
    """True when ``session_id`` still holds this item's live work claim."""
    response = dispatch(
        function_id=HOLDER_FUNCTION,
        target=public_item_target(item_id),
        payload={},
    )
    if not getattr(response, "success", False):
        return False
    result = getattr(response, "result", None) or {}
    holder = result.get("holder") if isinstance(result, dict) else None
    if not isinstance(holder, dict):
        return False
    return str(holder.get("session_id") or "") == session_id


def retain_for_delivery(
    envelope: dict[str, Any],
    *,
    item: Mapping[str, Any],
    item_id: int,
    public_ref: str,
    session_id: str,
) -> None:
    """Park the merging session on its own item's declared delivery wait.

    Mutates ``envelope`` in place with a ``release_wait`` block naming what
    the caller now holds, what the item owes delivery, and whether this
    session can be woken (:mod:`release_wait_facts`); the touch that parks
    the session returns the registered surface that wake fact is read from.
    The park is only stamped for a session that actually still holds the
    item's claim: an operator closing out somebody else's item is not the
    owner of this wait and must not be parked on it.

    Nothing here can fail the merge. The branch is already on the base
    branch and the item is already at its release wait by the time this
    runs, so an unreachable control plane is reported in the block and
    leaves the retention teaching to the outcome the caller prints.
    """
    reason = park_reason(public_ref)
    try:
        with connected_control_plane():
            obligation = delivery_obligation(item)
    except Exception as exc:  # noqa: BLE001 - reporting never fails a merge
        obligation = {"kind": OWES_UNREAD, "detail": str(exc)}
    block: dict[str, Any] = {
        "work_claim": "retained",
        "park_reason": reason,
        "session_mode": "",
        "obligation": obligation,
        "wake": session_wake(None),
        "next_step": _next_step(obligation, public_ref),
    }
    envelope["release_wait"] = block
    try:
        # Same fallback close_out_report.claim_state uses: the merge CLI
        # defaults --session-id to $YOKE_SESSION_ID, which the watcher
        # invocation leaves empty, while the process still has an ambient
        # session the park must stamp.
        session_id = session_id or str(resolve_ambient_session_id() or "")
        if not session_id:
            block["parked"] = "skipped: this run carries no session identity"
            return
        with connected_control_plane():
            if not _held_by(call_dispatcher, item_id, session_id):
                block["parked"] = (
                    "skipped: this session does not hold the item's work claim"
                )
                return
            response = call_dispatcher(
                function_id=TOUCH_FUNCTION,
                target=TargetRef(kind="global"),
                payload={"mode": SESSION_MODE_PARKED, "reason": reason},
                actor=build_actor(session_id=session_id),
            )
    except Exception as exc:  # noqa: BLE001 - reporting never fails a merge
        block["parked"] = f"unconfirmed ({exc})"
        return
    if not getattr(response, "success", False):
        error = getattr(response, "error", None)
        detail = getattr(error, "message", None) or f"{TOUCH_FUNCTION} refused"
        block["parked"] = f"unconfirmed ({detail})"
        return
    block["parked"] = "yes"
    block["session_mode"] = SESSION_MODE_PARKED
    result = getattr(response, "result", None)
    block["wake"] = session_wake(
        result.get("session") if isinstance(result, Mapping) else None
    )


def _next_step(obligation: Mapping[str, Any], public_ref: str) -> str:
    """The one re-entry this item's obligation actually asks for."""
    if obligation.get("kind") == OWES_NOTHING:
        return "none — delivery closes the item itself"
    if obligation.get("kind") == OWES_QA:
        return f"when the stage opens: {stage_recipe(obligation, public_ref)}"
    return (
        f"yoke merge item {public_ref} --result ... --verification ... "
        "— re-run when a wake names the delivery as cleared"
    )


__all__ = ["at_release_wait", "retain_for_delivery", "retain_if_waiting"]
