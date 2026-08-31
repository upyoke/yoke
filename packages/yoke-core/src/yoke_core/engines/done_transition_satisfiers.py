"""Done-transition satisfier ladders: how this item proved merge and delivery.

Two obligations discharge here, and both used to have a silent branch.

**Merge evidence.** The runner reached done with "No active worktree lane
and no branch found — continuing without a merge." printed to a
transcript nobody keeps. Afterwards the item said ``done`` and nothing
said how. Now the same three shapes resolve as three named rungs —
merged with a CI verdict, merged locally, or agent-attested because no
implementation branch ever existed — and the one that answered is
recorded on the item. An unmerged branch that *does* exist stops being
"skipping merge" and becomes a refusal.

**Delivery evidence.** An empty or ``*-internal`` ``deployment_flow``
returned clear from the deployment guard, so a workflow whose delivery
policy names a release could reach done having delivered nothing and
recorded nothing. A project that registers no deployment target really
does deliver by merging — that is the ``merge_only`` rung — but it is a
rung the item now carries, not an obligation that quietly evaporated.

Both resolve through the relayed ``gate_satisfier.rung.resolve``, so
they behave identically against a local Postgres connection and an https
control plane. A relay failure blocks: this engine must never conclude
"satisfied" from a read it could not make.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.gate_satisfier_facts import (
    OBSERVED_MERGE_RECORDED,
    OBSERVED_NO_IMPLEMENTATION_BRANCH,
)
from yoke_core.domain.gate_satisfier_ladder_catalog import (
    OBLIGATION_DELIVERY_EVIDENCE,
    OBLIGATION_DONE_MERGE_EVIDENCE,
)


class SatisfierRelayUnavailable(RuntimeError):
    """The ladder could not be resolved, so the transition must not proceed."""


def _resolve(
    item_id: int,
    obligation: str,
    observed: Dict[str, Tuple[bool, str]],
    *,
    target_status: str,
) -> Dict[str, Any]:
    resp = call_dispatcher(
        function_id="gate_satisfier.rung.resolve",
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "obligation": obligation,
            "target_status": target_status,
            "observed": {
                key: {"present": present, "detail": detail}
                for key, (present, detail) in observed.items()
            },
        },
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise SatisfierRelayUnavailable(
            f"gate_satisfier.rung.resolve failed for {obligation!r}: "
            f"{message}. The transition is refused rather than assumed "
            "satisfied — an unread ladder and a satisfied ladder are not "
            "the same answer."
        )
    return resp.result or {}


def _report(outcome: Dict[str, Any], heading: str) -> Optional[str]:
    """Print the satisfied rung, or return the refusal narrative to block on."""
    if outcome.get("satisfied"):
        print(
            f"{heading}: satisfied by rung '{outcome.get('rung_id')}' — "
            f"{outcome.get('detail')}"
        )
        if not outcome.get("stamp_recorded", True):
            print(
                f"  Warning: the rung resolved but was not recorded on the "
                "item. The transition stands on the resolution; re-run "
                "`yoke project snapshot sync` and check the item detail."
            )
        return None
    return str(outcome.get("refusal") or "").strip() or (
        f"{heading}: no satisfier was reachable and no narrative was "
        "returned; this is an engine defect in the ladder catalog."
    )


def check_merge_evidence(
    item_id: int,
    *,
    merge_ran: bool,
    branch_already_merged: bool,
    branch_exists: bool,
    target_status: str = "done",
) -> Optional[str]:
    """Resolve how this item's work reached the trunk, or return a refusal."""
    merged = bool(merge_ran or branch_already_merged)
    outcome = _resolve(
        item_id,
        OBLIGATION_DONE_MERGE_EVIDENCE,
        {
            OBSERVED_MERGE_RECORDED: (
                merged,
                "the lane branch merged during this transition"
                if merge_ran
                else (
                    "the lane branch was already merged"
                    if branch_already_merged
                    else "no merge ran and the branch is not merged"
                ),
            ),
            OBSERVED_NO_IMPLEMENTATION_BRANCH: (
                not branch_exists and not merged,
                "no implementation branch exists for this item"
                if not branch_exists
                else "an implementation branch exists for this item",
            ),
        },
        target_status=target_status,
    )
    return _report(outcome, "Merge evidence")


def check_delivery_evidence(
    item_id: int,
    *,
    merge_recorded: bool,
    target_status: str = "done",
) -> Optional[str]:
    """Resolve how this item delivered, or return a refusal.

    The succeeded-deployment-run half of the ladder is an item-scoped
    control-plane fact, so the server reads it; this call supplies only
    the merge fact, which is what the driving machine knows.
    """
    outcome = _resolve(
        item_id,
        OBLIGATION_DELIVERY_EVIDENCE,
        {
            OBSERVED_MERGE_RECORDED: (
                merge_recorded,
                "the item's work is recorded as merged"
                if merge_recorded
                else "no merge is recorded for this item",
            ),
        },
        target_status=target_status,
    )
    return _report(outcome, "Delivery evidence")


def check_done_satisfiers(
    item_id: int,
    *,
    merge_ran: bool,
    branch_already_merged: bool,
    branch_exists: bool,
) -> Optional[str]:
    """Resolve both done-stage obligations; return the first refusal.

    Merge evidence resolves first: delivery cannot be reasoned about
    until it is settled how — or whether — the work reached the trunk.
    A relay failure comes back as a refusal narrative too, because an
    unread ladder must block exactly like an unmet one.
    """
    try:
        block = check_merge_evidence(
            item_id,
            merge_ran=merge_ran,
            branch_already_merged=branch_already_merged,
            branch_exists=branch_exists,
        )
        if block:
            return block
        return check_delivery_evidence(
            item_id,
            merge_recorded=bool(merge_ran or branch_already_merged),
        )
    except SatisfierRelayUnavailable as exc:
        return str(exc)


__all__ = [
    "SatisfierRelayUnavailable",
    "check_delivery_evidence",
    "check_done_satisfiers",
    "check_merge_evidence",
]
