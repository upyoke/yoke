"""The merge boundary's terminal-transition step, split out of the CLI for
the authored-file line budget.

Landing at a pinned release wait instead of ``done`` is not a failure: the
merge is complete either way. Only a genuinely terminal result retires the
lane and claim, so a redirect to the release stage leaves both alone for a
later close-out (once delivery clears) to finish with authority.

Leaving them alone was not enough on its own. The retained claim belonged to
a session every other path was telling to release it and end, so the redirect
now also parks that session on the wait it just entered
(:mod:`release_wait_park`), which is what turns "the claim was not released"
into "the item still has an owner the deployment wake can reach".
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from yoke_core.domain.release_wait_park import retain_for_delivery
from yoke_core.domain.standalone_item_merge_landed import LandedLane
from yoke_core.domain.standalone_item_merge_release_status import (
    close_out_route,
)


def run_terminal_transition(
    *,
    item: dict[str, Any],
    item_id: int,
    public_ref: str,
    branch: str,
    target: str,
    status: str,
    close_lane: LandedLane,
    session_id: str,
    repo_root: Any,
    envelope: dict[str, Any],
    announce: Any,
    close_out: Any,
    evidence: Any,
    pending: Any,
    record_terminal_lane_close_out: Callable[..., Any],
    postpone_terminal: bool = False,
) -> Optional[int]:
    """Run the terminal transition, mutating ``envelope`` in place.

    Returns an exit code when the CLI should print ``envelope`` (or a
    substituted recovery envelope) and return immediately; ``None`` means
    the caller continues on to its own final print. The close-out
    collaborators are the caller's own bound names (module or patched
    callable) rather than fresh imports, so a caller's monkeypatch on any
    of them still reaches this call.
    """
    announce("terminal transition")
    route = close_out_route(item, status, postpone_terminal=postpone_terminal)
    if route.error:
        envelope["ok"] = False
        envelope["error"] = (
            f"merge landed and evidence recorded, but delivery clearance "
            f"could not be resolved: {route.error}"
        )
        return 1
    if not route.stages:
        # Mid-progress work (e.g. a still-implementing Blitz slice): the
        # pinned delivery will require a release wait eventually, but this
        # status cannot legally reach it yet, so nothing here applies.
        envelope["status"] = status
        return None
    new_status, transition_error = close_out.transition_to_done(
        item_id=item_id,
        source_status=status,
        repo_root=str(repo_root),
        lane=close_lane,
        session_id=session_id,
        stages=route.stages,
        delivery_discharged=route.delivery_discharged,
    )
    if transition_error:
        # A transition refused on an item another close-out has already
        # finished is a lost race, not a failure: the landing is complete
        # and the refusal's re-acquire hint would re-open a terminal item.
        recorded = evidence.recorded_landing_envelope(
            item_id, public_ref=public_ref, branch=branch,
        )
        if recorded is not None:
            record_terminal_lane_close_out(
                item,
                recorded,
                target_status=evidence.CLOSED_OUT_STATUS,
                session_id=session_id,
                repo_root=repo_root,
                target_branch=target,
            )
            envelope.clear()
            envelope.update(recorded)
            return 0
        envelope["ok"] = False
        envelope["error"] = (
            f"merge landed and evidence recorded, but the terminal "
            f"transition was refused: {transition_error}"
        )
        return 1
    envelope["status"] = new_status
    if new_status == evidence.CLOSED_OUT_STATUS:
        announce("lane cleanup")
        record_terminal_lane_close_out(
            {**item, "claim": None},
            envelope,
            target_status=evidence.CLOSED_OUT_STATUS,
            session_id=session_id,
            repo_root=repo_root,
            target_branch=target,
        )
        marker_error = pending.clear_after_close_out(item_id, item)
        if marker_error:
            envelope["warnings"].append(f"queue marker not cleared: {marker_error}")
        return None
    # The merge stopped at the pinned release wait, which still owes this item
    # a delivery and a done close-out. The session that merged it keeps the
    # claim and parks on that wait instead of reporting and ending.
    announce("release wait")
    retain_for_delivery(
        envelope,
        item_id=item_id,
        public_ref=public_ref,
        session_id=session_id,
    )
    return None


__all__ = ["run_terminal_transition"]
