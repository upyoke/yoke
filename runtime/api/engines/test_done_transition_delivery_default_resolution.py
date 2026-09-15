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

    def test_relay_failure_resolves_empty_rather_than_raising(self):
        response = SimpleNamespace(
            success=False, result={}, error=SimpleNamespace(message="unavailable"),
        )
        with mock.patch.object(
            delivery_default, "call_dispatcher", return_value=response
        ):
            assert (
                delivery_default.resolve_default_delivery_flow(
                    item_project="yoke", workflow_id="dash"
                )
                == ""
            )


class TestFreezeResolvedDeliveryFlow:
    def test_writes_the_resolved_flow_onto_the_item(self):
        response = SimpleNamespace(success=True, result={}, error=None)
        with mock.patch.object(
            delivery_default, "call_dispatcher", return_value=response
        ) as dispatch:
            delivery_default.freeze_resolved_delivery_flow(
                550, "ext-default", public_ref="EXT-550"
            )
        assert dispatch.call_args.kwargs["function_id"] == "items.scalar.update"
        assert dispatch.call_args.kwargs["payload"] == {
            "field": "deployment_flow",
            "value": "ext-default",
        }

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
