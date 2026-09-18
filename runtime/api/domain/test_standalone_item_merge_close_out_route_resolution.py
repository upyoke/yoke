"""Where a landed standalone merge's close-out takes the item.

The pinned definition owns the declared stage graph and the item's own
registered deployment flow owns whether delivery is still owed. Those two
readings disagreeing is what strands a merged item: a flow whose target tier
is null discharges delivery, while a release-bearing graph declares no edge
that skips its release wait, so a close-out that targets ``done`` directly
asks for a transition the definition never declared.
"""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain import deployment_flow_clearance as clearance
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
    monkeypatch.setattr(
        release_status, "delivery_has_discharged", lambda _item: answer,
    )


def test_a_merge_only_item_routes_through_the_declared_release_wait(
    monkeypatch,
) -> None:
    _serve(monkeypatch, "dash")
    _clearance(
        monkeypatch,
        DeliveryClearance(merge_only=True, resolved_flow=MERGE_ONLY_FLOW),
    )

    route = release_status.close_out_route(
        _item(workflow_id="dash", status="reviewing-implementation"),
        "reviewing-implementation",
    )

    assert route.error == ""
    assert route.stages == ("release", "done")
    assert route.delivery_discharged is True


def test_a_delivery_required_item_stops_at_its_release_wait(monkeypatch) -> None:
    _serve(monkeypatch, "dash")
    _clearance(
        monkeypatch,
        DeliveryClearance(merge_only=False, resolved_flow=DEPLOYING_FLOW),
    )

    route = release_status.close_out_route(
        _item(
            workflow_id="dash",
            status="reviewing-implementation",
            deployment_flow=DEPLOYING_FLOW,
        ),
        "reviewing-implementation",
    )

    assert route.stages == ("release",)
    assert route.delivery_discharged is False


def test_an_item_already_at_the_release_wait_carries_its_flows_verdict(
    monkeypatch,
) -> None:
    """Re-entry after a partial walk: the item stands at the release stage,
    and whether it may finish is still the flow's answer, not stage order."""
    _serve(monkeypatch, "dash")
    _clearance(
        monkeypatch,
        DeliveryClearance(merge_only=True, resolved_flow=MERGE_ONLY_FLOW),
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


def test_a_workflow_with_no_release_wait_closes_straight_out(monkeypatch) -> None:
    """A merge-free pin owns no release stage, so no flow is consulted and
    the close-out targets the terminal stage exactly as it always has."""
    _serve(monkeypatch, "task")
    monkeypatch.setattr(
        release_status,
        "resolve_delivery_clearance",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("a workflow with no release wait asks no flow")
        ),
    )

    route = release_status.close_out_route(
        _item(workflow_id="task", status="implementing"), "implementing",
    )

    assert route.stages == ("done",)
    assert route.delivery_discharged is False


def test_mid_progress_work_is_not_forced_into_an_early_release(
    monkeypatch,
) -> None:
    _serve(monkeypatch, "blitz")
    _clearance(
        monkeypatch,
        DeliveryClearance(merge_only=True, resolved_flow=MERGE_ONLY_FLOW),
    )

    route = release_status.close_out_route(
        _item(workflow_id="blitz", status="implementing"), "implementing",
    )

    assert route.stages == ()
    assert route.error == ""


def test_an_unresolved_flow_authority_refuses_rather_than_guessing(
    monkeypatch,
) -> None:
    _serve(monkeypatch, "dash")
    monkeypatch.setattr(
        release_status,
        "resolve_delivery_clearance",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("deployment_flows.get read failed: unavailable")
        ),
    )

    route = release_status.close_out_route(
        _item(workflow_id="dash", status="reviewing-implementation"),
        "reviewing-implementation",
    )

    assert route.stages == ()
    assert "deployment_flows.get read failed" in route.error


def test_no_configured_delivery_is_merge_only(monkeypatch) -> None:
    _serve(monkeypatch, "dash")
    _clearance(
        monkeypatch,
        DeliveryClearance(merge_only=True, resolved_flow=""),
    )

    route = release_status.close_out_route(
        _item(workflow_id="dash", status="reviewing-implementation"),
        "reviewing-implementation",
    )

    assert route.stages == ("release", "done")
    assert route.delivery_discharged is True
    assert route.error == ""


def test_the_shared_clearance_reader_is_the_one_authority(monkeypatch) -> None:
    """The route asks the item's own flow through the shared reader, so a
    registered merge-only flow -- never the flow id's spelling -- is what
    discharges delivery."""
    _serve(monkeypatch, "dash")
    monkeypatch.setattr(
        clearance, "registered_deployment_flow_ids", lambda: [MERGE_ONLY_FLOW],
    )
    monkeypatch.setattr(
        clearance, "deployment_flow_target_tier", lambda flow_id: "",
    )

    route = release_status.close_out_route(
        _item(
            workflow_id="dash",
            status="reviewing-implementation",
            deployment_flow=MERGE_ONLY_FLOW,
        ),
        "reviewing-implementation",
    )

    assert route.stages == ("release", "done")
    assert route.delivery_discharged is True


def test_an_already_closed_out_item_asks_no_delivery_authority(
    monkeypatch,
) -> None:
    """Re-entry on a finished item owes its lane a retirement, so an
    unconfigured flow must not turn that into a refusal on completed work."""
    monkeypatch.setattr(
        readiness,
        "call_dispatcher",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("a closed-out item needs no definition read")
        ),
    )
    monkeypatch.setattr(
        release_status,
        "resolve_delivery_clearance",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("a closed-out item asks no delivery authority")
        ),
    )

    route = release_status.close_out_route(
        _item(workflow_id="dash", status="done"), "done",
    )

    assert route.stages == ("done",)
    assert route.error == ""


def test_skip_status_enters_release_instead_of_walking_to_done(monkeypatch) -> None:
    _serve(monkeypatch, "dash")
    _clearance(
        monkeypatch,
        DeliveryClearance(merge_only=True, resolved_flow=MERGE_ONLY_FLOW),
    )

    route = release_status.close_out_route(
        _item(workflow_id="dash", status="reviewing-implementation"),
        "reviewing-implementation",
        postpone_terminal=True,
    )

    assert route.error == ""
    assert route.stages == ("release",)
    assert route.delivery_discharged is False


def test_skip_status_does_not_leave_an_item_already_at_release(monkeypatch) -> None:
    _serve(monkeypatch, "dash")

    route = release_status.close_out_route(
        _item(workflow_id="dash", status="release"),
        "release",
        postpone_terminal=True,
    )

    assert route.stages == ()
    assert route.error == ""


def test_skip_status_is_a_noop_on_a_workflow_with_no_release_wait(
    monkeypatch,
) -> None:
    _serve(monkeypatch, "task")

    route = release_status.close_out_route(
        _item(workflow_id="task", status="implementing"),
        "implementing",
        postpone_terminal=True,
    )

    assert route.stages == ()
    assert route.error == ""
