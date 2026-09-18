"""Whether a delivery actually happened, asked from the merge boundary.

The close-out route needs this to decide whether re-entering at a release
wait performs the done ceremony or still owes one. It is a relayed read, so
these pin the two things a caller cannot see from the answer alone: which
fact it asks for, and which way it fails.
"""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain.delivery_discharge_read import delivery_has_discharged


DEPLOYING_FLOW = "production-release"


def _item() -> dict:
    return {
        "id": 41,
        "public_ref": "ITEM-41",
        "status": "release",
        "workflow": {"id": "dash", "version": 3},
        "deployment_flow": DEPLOYING_FLOW,
        "project": {"slug": "acme"},
    }


def test_an_unreadable_delivery_answer_does_not_assert_the_ceremony() -> None:
    """Fail closed: an unread delivery leaves the item at its release wait.

    Asserting a ceremony nobody performed is the one direction this read
    must never fail in, so a refused or unreachable relay answers ``False``
    rather than raising into the merge boundary.
    """
    def _raises(**_kwargs):
        raise RuntimeError("relay down")

    def _refuses(**_kwargs):
        return SimpleNamespace(success=False, result=None, error="nope")

    item = _item()
    assert delivery_has_discharged(item, dispatch=_raises) is False
    assert delivery_has_discharged(item, dispatch=_refuses) is False
    assert delivery_has_discharged({}, dispatch=_raises) is False


def test_a_discharged_delivery_reads_through_the_shared_ladder() -> None:
    """One fact, asked of the one place that answers it."""
    asked: dict = {}

    def _dispatch(*, function_id, target, payload):
        asked["function_id"] = function_id
        asked["item_id"] = target.item_id
        return SimpleNamespace(
            success=True, result={"state": "discharged"}, error=None,
        )

    item = _item()
    assert delivery_has_discharged(item, dispatch=_dispatch) is True
    assert asked["function_id"] == "done_transition.delivery_evidence"
    assert asked["item_id"] == item["id"]
