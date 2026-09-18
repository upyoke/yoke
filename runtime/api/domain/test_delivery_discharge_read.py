"""Whether a delivery actually happened, asked from the merge boundary.

The close-out route needs this to decide whether re-entering at a release
wait performs the done ceremony or still owes one. It is a relayed read, so
these pin what a caller cannot see from the answer alone: which fact it asks
for, and that a read which could not run says so rather than passing for a
no.
"""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain.delivery_discharge_read import delivery_discharge


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


def _answer(payload):
    return lambda **_kwargs: SimpleNamespace(
        success=True, result=payload, error=None,
    )


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
    verdict = delivery_discharge(item, dispatch=_dispatch)
    assert verdict.discharged is True
    assert verdict.unread is False
    assert asked["function_id"] == "done_transition.delivery_evidence"
    assert asked["item_id"] == item["id"]


def test_an_undelivered_item_is_a_real_no() -> None:
    verdict = delivery_discharge(
        _item(),
        dispatch=_answer({"state": "not_discharged", "reason": "no run yet"}),
    )
    assert verdict.discharged is False
    assert verdict.unread is False
    assert verdict.detail == "no run yet"


def test_a_read_that_could_not_run_is_unread_rather_than_a_no() -> None:
    """The distinction the undiagnosable nonce refusal used to lose.

    Fail-closed is still fail-closed — unread never asserts the ceremony —
    but it has to be visible, or the owner is told to perform a ceremony
    nobody can perform and never learns the read is what broke.
    """

    def _raises(**_kwargs):
        raise RuntimeError("relay down")

    def _refuses(**_kwargs):
        return SimpleNamespace(
            success=False, result=None, error=SimpleNamespace(message="denied"),
        )

    item = _item()
    for dispatch in (_raises, _refuses):
        verdict = delivery_discharge(item, dispatch=dispatch)
        assert verdict.unread is True
        assert verdict.discharged is False
        assert verdict.detail
        assert verdict.recovery

    raised = delivery_discharge(item, dispatch=_raises)
    assert "relay down" in raised.detail
    refused = delivery_discharge(item, dispatch=_refuses)
    assert "denied" in refused.detail


def test_an_undetermined_ladder_verdict_keeps_its_own_diagnosis() -> None:
    """The ladder already named the provider failure; do not discard it."""
    verdict = delivery_discharge(
        _item(),
        dispatch=_answer({
            "state": "undetermined",
            "reason": "repository_provider_read_failed",
            "recovery": "Confirm the project's GitHub binding, then retry.",
        }),
    )
    assert verdict.unread is True
    assert "repository_provider_read_failed" in verdict.detail
    assert "GitHub binding" in verdict.recovery


def test_a_missing_id_or_verdict_is_unread() -> None:
    assert delivery_discharge({}, dispatch=_answer({})).unread is True
    assert delivery_discharge(_item(), dispatch=_answer({})).unread is True
