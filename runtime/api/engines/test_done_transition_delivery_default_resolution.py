"""Resolving and freezing a project's delivery default onto an empty item."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_core.engines import done_transition_delivery_default as delivery_default


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
        with mock.patch.object(
            delivery_default, "call_dispatcher", return_value=response
        ):
            assert (
                delivery_default.resolve_default_delivery_flow(
                    item_project="externalwebapp", workflow_id="dash"
                )
                == "ext-default"
            )

    def test_no_match_and_empty_workflow_id_both_resolve_empty(self):
        response = SimpleNamespace(
            success=True, result={"delivery_defaults": []}, error=None,
        )
        with mock.patch.object(
            delivery_default, "call_dispatcher", return_value=response
        ):
            assert (
                delivery_default.resolve_default_delivery_flow(
                    item_project="externalwebapp", workflow_id="dash"
                )
                == ""
            )
        assert (
            delivery_default.resolve_default_delivery_flow(
                item_project="externalwebapp", workflow_id=""
            )
            == ""
        )

    def test_relay_failure_raises_rather_than_reading_as_no_config(self):
        response = SimpleNamespace(
            success=False, result={}, error=SimpleNamespace(message="unavailable"),
        )
        with mock.patch.object(
            delivery_default, "call_dispatcher", return_value=response
        ):
            with pytest.raises(RuntimeError, match="unavailable"):
                delivery_default.resolve_default_delivery_flow(
                    item_project="yoke", workflow_id="dash"
                )


class TestFreezeResolvedDeliveryFlow:
    def test_writes_the_resolved_flow_onto_the_item(self):
        response = SimpleNamespace(
            success=True,
            result={"item_id": 550, "deployment_flow": "ext-default", "claimed": True},
            error=None,
        )
        with mock.patch.object(
            delivery_default, "call_dispatcher", return_value=response
        ) as dispatch:
            result = delivery_default.freeze_resolved_delivery_flow(
                550, "ext-default", public_ref="EXT-550"
            )
        assert result == "ext-default"
        assert (
            dispatch.call_args.kwargs["function_id"]
            == "items.deployment_flow.claim_default"
        )
        assert dispatch.call_args.kwargs["payload"] == {"flow_id": "ext-default"}

    def test_a_refused_write_raises(self):
        response = SimpleNamespace(
            success=False, result={}, error=SimpleNamespace(message="frozen item"),
        )
        with mock.patch.object(
            delivery_default, "call_dispatcher", return_value=response
        ):
            with pytest.raises(RuntimeError, match="frozen item"):
                delivery_default.freeze_resolved_delivery_flow(
                    551, "ext-default", public_ref="EXT-551"
                )

    def test_a_value_raced_in_since_the_callers_earlier_read_wins(self):
        """The conditional UPDATE inside claim_default did not apply
        (claimed=False), so the response's own reread value -- not the
        resolved candidate this call offered -- is the winning one."""
        response = SimpleNamespace(
            success=True,
            result={
                "item_id": 552,
                "deployment_flow": "raced-in-value",
                "claimed": False,
            },
            error=None,
        )
        with mock.patch.object(
            delivery_default, "call_dispatcher", return_value=response
        ) as dispatch:
            result = delivery_default.freeze_resolved_delivery_flow(
                552, "ext-default", public_ref="EXT-552"
            )
        assert result == "raced-in-value"
        dispatch.assert_called_once()
