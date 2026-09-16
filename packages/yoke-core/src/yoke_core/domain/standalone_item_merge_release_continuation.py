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
is reported as a warning and the registered continuation can finish the job,
since it re-derives everything it needs from durable rows.

The ask itself is the registered ``deployment_runs.continue_for_item``
function, relayed over the bound close-out connection. Ordinary HTTPS
projects stay on that connection; a local or self-hosted universe still
dispatches in-process. This module never opens a control-plane database and
never names a db-admin retry. Serving-API self-deploy restrictions stay on
the execute path — continuation only binds lineage and hands off.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.close_out_control_plane_authority import connected_control_plane
from yoke_core.domain.control_plane_transport import relay
from yoke_core.engines.runs_continue_for_item import (
    OUTCOME_BOUND,
    OUTCOME_NONE,
    OUTCOME_WAITING,
)

CONTINUE_FUNCTION = "deployment_runs.continue_for_item"


def _item_target(item_id: int, public_ref: str) -> TargetRef:
    named = public_ref.strip()
    return TargetRef(
        kind="item",
        item_id=int(item_id),
        public_ref=named or None,
    )


def _inspect_clause(public_ref: str) -> str:
    named = public_ref.strip()
    if not named:
        return (
            " Inspect with `yoke deployment-runs find-by-item` or resume with "
            "`yoke deployment-runs continue-for-item`."
        )
    return (
        f" Inspect with `yoke deployment-runs find-by-item {named}` or resume "
        f"with `yoke deployment-runs continue-for-item {named}`."
    )


def _explicit_warning(message: str, *, public_ref: str) -> str:
    return (
        f"{message} The merge is complete; this is not a merge failure."
        f"{_inspect_clause(public_ref)}"
    )


def _fragment(
    result: dict[str, Any], *, public_ref: str,
) -> tuple[dict[str, Any], str]:
    fragment: dict[str, Any] = {
        "run_id": result.get("run_id"),
        "outcome": result.get("outcome"),
    }
    runs = result.get("runs")
    if runs:
        fragment["runs"] = list(runs)
    if result.get("outcome") == OUTCOME_WAITING:
        fragment["waiting_on"] = list(result.get("waiting_on") or [])
        return fragment, ""
    if result.get("outcome") == OUTCOME_BOUND:
        fragment["release_lineage"] = result.get("release_lineage")
        fragment["handed_off_to"] = result.get("handed_off_to")
        if not result.get("message_id"):
            resume = _inspect_clause(public_ref).strip()
            return fragment, (
                f"prepared run {result.get('run_id')} now names "
                f"{result.get('release_lineage')} but the hand-off to the "
                f"deploy authority was not delivered. {resume}"
            )
        fragment["message_id"] = result.get("message_id")
    return fragment, ""


def continue_prepared_release(
    *,
    item_id: int,
    session_id: str = "",
    public_ref: str = "",
) -> tuple[Optional[dict[str, Any]], str]:
    """Advance a prepared release this merge may complete.

    Returns ``(envelope_fragment, warning)``. Both are empty when no prepared
    run is waiting on this item, which is the ordinary case. *session_id* is
    accepted so merge close-out can pass the session it already resolved; the
    relay binds the ambient actor, which is that same session.
    """
    del session_id
    named = (public_ref or "").strip()
    try:
        with connected_control_plane():
            result = relay(CONTINUE_FUNCTION, {}, _item_target(item_id, named))
    except Exception as exc:
        return None, _explicit_warning(
            f"prepared release continuation could not be evaluated: {exc}.",
            public_ref=named,
        )
    if result.get("ok") is False:
        return None, _explicit_warning(
            f"prepared release not advanced: {result.get('error')}.",
            public_ref=named,
        )
    if result.get("outcome") == OUTCOME_NONE:
        return None, ""
    return _fragment(result, public_ref=named)


__all__ = ["CONTINUE_FUNCTION", "continue_prepared_release"]
