"""How the close-out route treats a delivery answer it could not read.

Split from the route-resolution suite, which covers the stage graph and the
flow clearance. These cover one axis: an unread delivery must refuse by name
rather than pass for "not delivered", because the route that walks on
without the ceremony hands the owner a refusal nothing can act on.
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

    monkeypatch.setattr(
        release_status,
        "delivery_discharge",
        lambda _item: DeliveryDischarge(DISCHARGED if answer else NOT_DISCHARGED),
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


def test_a_deploying_flow_still_awaiting_its_delivery_is_not_discharged(
    monkeypatch,
) -> None:
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

    assert route.stages == ("done",)
    assert route.delivery_discharged is False


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
