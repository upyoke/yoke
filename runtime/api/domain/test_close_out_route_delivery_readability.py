"""How the close-out route treats what the delivery read told it.

Split from the route-resolution suite, which covers the stage graph and the
flow clearance. These cover one axis: the three delivery answers reaching
this boundary have three outcomes. An unread delivery must refuse by name
rather than pass for "not delivered"; a delivery that definitely has not
happened must hold the item at its release wait and name the run it waits
on; only a delivery that happened may walk to the terminal stage. Either of
the first two walking on without the ceremony hands the owner a
"missing done-transition ceremony nonce" refusal nothing can act on.
"""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain import merge_review_readiness as readiness
from yoke_core.domain import standalone_item_merge_release_status as release_status
from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definition
from yoke_core.domain.deployment_flow_clearance import DeliveryClearance
from yoke_core.domain.workflow_registry import definition_digest

MERGE_ONLY_FLOW = "internal"
DEPLOYING_FLOW = "production-release"


def _item(*, workflow_id: str, status: str, deployment_flow: str = "") -> dict:
    return {
        "id": 41,
        "public_ref": "ITEM-41",
        "status": status,
        "workflow": {"id": workflow_id, "version": 3},
        "deployment_flow": deployment_flow,
        "project": {"slug": "acme"},
    }


def _serve(monkeypatch, workflow_id: str) -> None:
    definition = builtin_workflow_definition(workflow_id)["definition"]
    response = SimpleNamespace(
        success=True,
        error=None,
        result={
            "workflow_id": workflow_id,
            "version": 3,
            "version_id": 300,
            "definition": definition,
            "definition_digest": definition_digest(definition),
        },
    )
    monkeypatch.setattr(readiness, "call_dispatcher", lambda **_kwargs: response)


def _clearance(monkeypatch, verdict: DeliveryClearance) -> None:
    monkeypatch.setattr(
        release_status, "resolve_delivery_clearance", lambda **_kwargs: verdict,
    )


def _discharged(monkeypatch, answer: bool) -> None:
    """Whether a succeeded run of the item's selected flow delivered it."""
    from yoke_core.domain.delivery_discharge_read import (
        DISCHARGED,
        NOT_DISCHARGED,
        DeliveryDischarge,
    )

    verdict = (
        DeliveryDischarge(DISCHARGED)
        if answer
        else DeliveryDischarge(
            NOT_DISCHARGED,
            detail="the selected flow's latest run is at status 'executing'",
            recovery="Execute or retry deployment run run-20260919-020.",
            run_id="run-20260919-020",
            run_status="executing",
        )
    )
    monkeypatch.setattr(
        release_status, "delivery_discharge", lambda _item: verdict,
    )


def _unread_delivery(monkeypatch) -> None:
    """A delivery answer the control plane could not produce."""
    from yoke_core.domain.delivery_discharge_read import UNREAD, DeliveryDischarge

    monkeypatch.setattr(
        release_status,
        "delivery_discharge",
        lambda _item: DeliveryDischarge(
            UNREAD, detail="the relay refused", recovery="Restore it, then retry.",
        ),
    )


def test_an_unread_delivery_refuses_by_name_rather_than_reading_as_undelivered(
    monkeypatch,
) -> None:
    """Fail loudly: an unread delivery is neither yes nor no.

    Letting it pass for "not delivered" walks the route to the terminal
    stage without the ceremony and hands the owner the undiagnosable
    "missing done-transition ceremony nonce" refusal — the exact failure
    this ladder exists to remove.
    """
    _serve(monkeypatch, "dash")
    _clearance(
        monkeypatch,
        DeliveryClearance(merge_only=False, resolved_flow=DEPLOYING_FLOW),
    )
    _unread_delivery(monkeypatch)

    route = release_status.close_out_route(
        _item(workflow_id="dash", status="release", deployment_flow=DEPLOYING_FLOW),
        "release",
    )

    assert route.stages == ()
    assert route.delivery_discharged is False
    assert "could not be read" in route.error
    assert "the relay refused" in route.error
    assert "Restore it, then retry." in route.error


def test_a_merge_only_item_never_asks_the_delivery_authority(monkeypatch) -> None:
    """Its merge WAS the delivery, so there is no run to read about."""
    _serve(monkeypatch, "dash")
    _clearance(
        monkeypatch,
        DeliveryClearance(merge_only=True, resolved_flow=MERGE_ONLY_FLOW),
    )
    monkeypatch.setattr(
        release_status,
        "delivery_discharge",
        lambda _item: (_ for _ in ()).throw(
            AssertionError("merge-only must not read delivery evidence")
        ),
    )

    route = release_status.close_out_route(
        _item(workflow_id="dash", status="release"), "release",
    )

    assert route.stages == ("done",)
    assert route.delivery_discharged is True


def test_an_undelivered_item_is_held_at_its_wait_with_the_run_named(
    monkeypatch,
) -> None:
    """The definite "not delivered" case is an answer, not a failed read.

    Walking to the terminal stage here spent the transition on a ceremony
    only a deploy can perform, and the engine refused with the missing
    done-transition nonce — which told the owner to re-run the command that
    had just run, and said nothing about the run they were waiting on.
    """
    _serve(monkeypatch, "dash")
    _clearance(
        monkeypatch,
        DeliveryClearance(merge_only=False, resolved_flow=DEPLOYING_FLOW),
    )
    _discharged(monkeypatch, False)

    route = release_status.close_out_route(
        _item(
            workflow_id="dash", status="release", deployment_flow=DEPLOYING_FLOW,
        ),
        "release",
    )

    assert route.stages == ()
    assert route.delivery_discharged is False
    # Not an error: the clearance resolved, and it resolved to "not yet".
    assert route.error == ""
    assert DEPLOYING_FLOW in route.delivery_pending
    assert "run-20260919-020" in route.delivery_pending
    assert "executing" in route.delivery_pending
    assert "Execute or retry deployment run run-20260919-020." in (
        route.delivery_pending
    )
    assert "nonce" not in route.delivery_pending


def test_an_undelivered_item_with_no_run_still_names_what_it_waits_on(
    monkeypatch,
) -> None:
    """No run carries the merge yet, so the ladder's own reason leads."""
    from yoke_core.domain.delivery_discharge_read import (
        NOT_DISCHARGED,
        DeliveryDischarge,
    )

    _serve(monkeypatch, "dash")
    _clearance(
        monkeypatch,
        DeliveryClearance(merge_only=False, resolved_flow=DEPLOYING_FLOW),
    )
    monkeypatch.setattr(
        release_status,
        "delivery_discharge",
        lambda _item: DeliveryDischarge(
            NOT_DISCHARGED,
            detail=(
                "no succeeded release that ships this project contains this "
                "merge"
            ),
            recovery="Run the selected project delivery flow to completion.",
        ),
    )

    route = release_status.close_out_route(
        _item(
            workflow_id="dash", status="release", deployment_flow=DEPLOYING_FLOW,
        ),
        "release",
    )

    assert route.stages == ()
    assert route.error == ""
    assert "no succeeded release" in route.delivery_pending
    assert "deployment run" not in route.delivery_pending
    assert "Run the selected project delivery flow to completion." in (
        route.delivery_pending
    )


def test_a_deploying_flow_whose_delivery_succeeded_is_discharged(
    monkeypatch,
) -> None:
    """The ceremony is owed to a deploy, and that deploy has happened.

    Keying this on ``merge_only`` asserted the ceremony for exactly the items
    that never owed a deploy and withheld it from every item whose deploy had
    just succeeded, so a delivered member recorded its evidence and was then
    refused ``done`` for a ceremony no command could perform.
    """
    _serve(monkeypatch, "dash")
    _clearance(
        monkeypatch,
        DeliveryClearance(merge_only=False, resolved_flow=DEPLOYING_FLOW),
    )
    _discharged(monkeypatch, True)

    route = release_status.close_out_route(
        _item(
            workflow_id="dash", status="release", deployment_flow=DEPLOYING_FLOW,
        ),
        "release",
    )

    assert route.stages == ("done",)
    assert route.delivery_discharged is True
    assert route.delivery_pending == ""
