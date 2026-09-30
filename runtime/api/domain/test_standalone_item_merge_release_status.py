"""Whether an item's own status has reached its pinned release wait."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain import deployment_flow_clearance as clearance
from yoke_core.domain import merge_review_readiness as readiness
from yoke_core.domain import standalone_item_merge_release_status as release_status
from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definition
from yoke_core.domain.item_completion_flow_projection import flow_id
from yoke_core.domain.workflow_registry import definition_digest


def _item(*, workflow_id: str, status: str) -> dict:
    return {
        "id": 41,
        "public_ref": "ITEM-41",
        "status": status,
        "workflow": {"id": workflow_id, "version": 3},
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


def test_an_item_still_implementing_has_not_reached_release(monkeypatch) -> None:
    _serve(monkeypatch, "dash")

    assert (
        release_status.reached_release(
            _item(workflow_id="dash", status="implementing"), "implementing"
        )
        is False
    )


def test_a_closed_out_dash_item_treats_mismatch_as_foreign(monkeypatch) -> None:
    _serve(monkeypatch, "dash")

    assert (
        release_status.stale_mismatch_is_foreign(
            _item(workflow_id="dash", status="done"), "done"
        )
        is True
    )


def test_a_dash_item_at_release_keeps_same_item_mismatch(monkeypatch) -> None:
    _serve(monkeypatch, "dash")

    assert (
        release_status.stale_mismatch_is_foreign(
            _item(workflow_id="dash", status="release"), "release"
        )
        is False
    )
    assert (
        release_status.reached_release(
            _item(workflow_id="dash", status="release"), "release"
        )
        is True
    )


def test_a_task_pin_still_treats_mismatch_as_foreign(monkeypatch) -> None:
    _serve(monkeypatch, "task")

    assert (
        release_status.stale_mismatch_is_foreign(
            _item(workflow_id="task", status="implementing"), "implementing"
        )
        is True
    )


def test_a_workflow_with_no_release_stage_defaults_true(monkeypatch) -> None:
    """Task/merge-only pins own no release wait at all; this stays out of
    their existing behavior entirely."""
    _serve(monkeypatch, "task")

    assert (
        release_status.reached_release(
            _item(workflow_id="task", status="implementing"), "implementing"
        )
        is True
    )


def test_an_unreadable_definition_defaults_true(monkeypatch) -> None:
    """Fails closed, matching review_readiness_refusal's own convention: a
    read that could not be answered must not answer as a bypass."""
    response = SimpleNamespace(
        success=False,
        error=SimpleNamespace(message="unavailable"),
        result={},
    )
    monkeypatch.setattr(readiness, "call_dispatcher", lambda **_kwargs: response)

    assert (
        release_status.reached_release(
            _item(workflow_id="dash", status="implementing"), "implementing"
        )
        is True
    )


def _clear_flows(monkeypatch, flow: str, tier: str) -> list[str]:
    """Serve the flow registry and record every flow the clearance checked."""
    checked: list[str] = []

    def _registered() -> list[str]:
        return [flow]

    def _tier(deploy_flow: str) -> str:
        checked.append(deploy_flow)
        return tier

    monkeypatch.setattr(clearance, "registered_deployment_flow_ids", _registered)
    monkeypatch.setattr(clearance, "deployment_flow_target_tier", _tier)
    return checked


def _reviewed_item(deployment_flow) -> dict:
    return {
        **_item(workflow_id="dash", status="reviewing-implementation"),
        "project": {"slug": "yoke"},
        "deployment_flow": deployment_flow,
    }


def test_close_out_reads_the_projected_flow_mapping(monkeypatch) -> None:
    """The item read projects ``deployment_flow`` as ``{value, source}``.

    Stringifying that mapping handed the clearance a flow id nothing
    registers, so every merge close-out refused as an unregistered flow.
    """
    _serve(monkeypatch, "dash")
    checked = _clear_flows(monkeypatch, "flow-release", "production")
    item = _reviewed_item({"value": "flow-release", "source": "project_default"})

    route = release_status.close_out_route(item, "reviewing-implementation")

    assert route.error == ""
    assert route.stages == ("release",)
    assert checked == ["flow-release"]


def test_close_out_reads_a_bare_flow_string(monkeypatch) -> None:
    """A serving build older than the projection returns the bare pin."""
    _serve(monkeypatch, "dash")
    checked = _clear_flows(monkeypatch, "flow-release", "production")
    item = _reviewed_item("flow-release")

    route = release_status.close_out_route(item, "reviewing-implementation")

    assert route.error == ""
    assert route.stages == ("release",)
    assert checked == ["flow-release"]


def test_flow_id_accepts_both_read_shapes() -> None:
    assert flow_id({"value": "flow-release", "source": "item"}) == "flow-release"
    assert flow_id({"value": "", "source": "none"}) == ""
    assert flow_id(" flow-release ") == "flow-release"
    assert flow_id(None) == ""
