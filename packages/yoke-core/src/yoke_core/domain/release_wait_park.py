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
from yoke_core.domain.session_mode import SESSION_MODE_PARKED


def _held_by(dispatch: Any, item_id: int, session_id: str) -> bool:
    """True when ``session_id`` still holds this item's live work claim."""
    response = dispatch(
        function_id=HOLDER_FUNCTION,
        target=TargetRef(kind="item", item_id=int(item_id)),
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
    item_id: int,
    public_ref: str,
    session_id: str,
) -> None:
    """Park the merging session on its own item's declared delivery wait.

    Mutates ``envelope`` in place with a ``release_wait`` block naming what
    the caller now holds and what re-enters it. The park is only stamped for
    a session that actually still holds the item's claim: an operator
    closing out somebody else's item is not the owner of this wait and must
    not be parked on it.

    Nothing here can fail the merge. The branch is already on the base
    branch and the item is already at its release wait by the time this
    runs, so an unreachable control plane is reported in the block and
    leaves the retention teaching to the outcome the caller prints.
    """
    reason = park_reason(public_ref)
    block: dict[str, Any] = {
        "work_claim": "retained",
        "park_reason": reason,
        "session_mode": "",
        "next_step": (
            f"yoke merge item {public_ref} --result ... --verification ... "
            "— re-run when the deployment wake says the delivery cleared"
        ),
    }
    envelope["release_wait"] = block
    if not session_id:
        block["parked"] = "skipped: this run carries no session identity"
        return
    try:
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


__all__ = ["retain_for_delivery"]
