"""Whether a deployment flow discharges delivery without a release wait.

Shared by the done-transition engine's deployment-flow guard and the
standalone merge boundary's terminal transition -- see the module docstring
for why an empty ``deployment_flow`` scalar is never itself the merge-only
signal, and why an arbitrary flow id is checked against the registry and
its own ``target_tier`` rather than a naming convention.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_core.domain import deployment_flow_clearance as clearance


class TestResolveDefaultDeliveryFlow:
    def test_matches_project_and_workflow_from_the_mechanics_read(self):
        response = SimpleNamespace(
            success=True,
            result={
                "delivery_defaults": [
                    {"project": "yoke", "workflow_id": "dash", "flow_id": "yoke-default"},
                    {"project": "externalwebapp", "workflow_id": "dash", "flow_id": "ext-default"},
                ]
            },
            error=None,
        )
        with mock.patch.object(clearance, "call_dispatcher", return_value=response):
            assert (
                clearance.resolve_default_delivery_flow(
                    item_project="externalwebapp", workflow_id="dash"
                )
                == "ext-default"
            )

    def test_no_match_and_empty_workflow_id_both_resolve_empty(self):
        response = SimpleNamespace(
            success=True, result={"delivery_defaults": []}, error=None,
        )
        with mock.patch.object(clearance, "call_dispatcher", return_value=response):
            assert (
                clearance.resolve_default_delivery_flow(
                    item_project="externalwebapp", workflow_id="dash"
                )
                == ""
            )
        assert (
            clearance.resolve_default_delivery_flow(
                item_project="externalwebapp", workflow_id=""
            )
            == ""
        )

    def test_relay_failure_raises_rather_than_reading_as_no_config(self):
        response = SimpleNamespace(
            success=False, result={}, error=SimpleNamespace(message="unavailable"),
        )
        with mock.patch.object(clearance, "call_dispatcher", return_value=response):
            with pytest.raises(RuntimeError, match="unavailable"):
                clearance.resolve_default_delivery_flow(
                    item_project="yoke", workflow_id="dash"
                )


def _dispatch(answers: dict[str, object]):
    def dispatch(*, function_id, payload=None, **_kw):
        if function_id not in answers:
            raise AssertionError(f"unexpected read: {function_id}")
        return SimpleNamespace(success=True, result=answers[function_id], error=None)

    return dispatch


class TestResolveDeliveryClearance:
    def test_an_arbitrary_named_flow_with_a_real_target_tier_is_not_merge_only(
        self, monkeypatch,
    ):
        """Naming alone never decides this -- only the registry and tier do."""
        monkeypatch.setattr(
            clearance,
            "call_dispatcher",
            _dispatch(
                {
                    "done_transition.registered_flow_ids": {"flow_ids": ["acme-prod"]},
                    "deployment_flows.get": {"value": "production"},
                }
            ),
        )
        result = clearance.resolve_delivery_clearance(
            deploy_flow="acme-prod", item_project="yoke", workflow_id="dash",
        )
        assert result.merge_only is False
        assert result.resolved_flow == "acme-prod"
        assert result.blocked_reason == ""

    def test_an_arbitrary_named_flow_with_a_null_target_tier_is_merge_only(
        self, monkeypatch,
    ):
        monkeypatch.setattr(
            clearance,
            "call_dispatcher",
            _dispatch(
                {
                    "done_transition.registered_flow_ids": {"flow_ids": ["acme-runless"]},
                    "deployment_flows.get": {"value": None},
                }
            ),
        )
        result = clearance.resolve_delivery_clearance(
            deploy_flow="acme-runless", item_project="yoke", workflow_id="dash",
        )
        assert result.merge_only is True
        assert result.resolved_flow == "acme-runless"

    def test_an_unregistered_flow_id_is_blocked_rather_than_merge_only(
        self, monkeypatch,
    ):
        monkeypatch.setattr(
            clearance,
            "call_dispatcher",
            _dispatch({"done_transition.registered_flow_ids": {"flow_ids": []}}),
        )
        result = clearance.resolve_delivery_clearance(
            deploy_flow="typo-d-flow", item_project="yoke", workflow_id="dash",
        )
        assert result.merge_only is False
        assert "not a registered deployment flow" in result.blocked_reason

    def test_an_internal_suffixed_flow_stays_merge_only_by_its_own_convention(
        self, monkeypatch,
    ):
        monkeypatch.setattr(
            clearance,
            "call_dispatcher",
            lambda **_k: (_ for _ in ()).throw(
                AssertionError("an -internal flow needs no registry or tier read")
            ),
        )
        result = clearance.resolve_delivery_clearance(
            deploy_flow="dash-internal", item_project="yoke", workflow_id="dash",
        )
        assert result.merge_only is True

    def test_an_empty_flow_resolves_the_project_default_before_any_verdict(
        self, monkeypatch,
    ):
        """A new item's blank scalar is not itself a merge-only signal."""
        monkeypatch.setattr(
            clearance,
            "call_dispatcher",
            _dispatch(
                {
                    "workflows.mechanics.get": {
                        "delivery_defaults": [
                            {"project": "yoke", "workflow_id": "dash", "flow_id": "yoke-default"}
                        ]
                    },
                    "done_transition.registered_flow_ids": {"flow_ids": ["yoke-default"]},
                    "deployment_flows.get": {"value": "production"},
                }
            ),
        )
        result = clearance.resolve_delivery_clearance(
            deploy_flow="", item_project="yoke", workflow_id="dash",
        )
        assert result.merge_only is False
        assert result.resolved_flow == "yoke-default"

    def test_an_empty_flow_with_no_configured_default_is_blocked(self, monkeypatch):
        monkeypatch.setattr(
            clearance,
            "call_dispatcher",
            _dispatch({"workflows.mechanics.get": {"delivery_defaults": []}}),
        )
        result = clearance.resolve_delivery_clearance(
            deploy_flow="", item_project="yoke", workflow_id="dash",
        )
        assert result.merge_only is False
        assert result.resolved_flow == ""
        assert "no deployment flow selected" in result.blocked_reason
