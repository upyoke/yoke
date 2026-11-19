"""The client half of delivery clearance: one project-scoped read.

The verdict itself (project default, registration, target tier) is resolved
on the server -- see ``handlers/test_done_transition_delivery_clearance_read``.
These tests pin what the close-outs send and how they treat the answer: an
unread or malformed answer raises rather than reading as merge-only, and no
close-out path reaches for the org-admin ``workflows.mechanics.get`` or
``deployment_flows.get`` reads.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import deployment_flow_clearance as clearance


def _recorder(result=None, *, success=True, message=""):
    calls: list[dict] = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            success=success,
            result=result if result is not None else {},
            error=None if success else SimpleNamespace(message=message),
        )

    return dispatch, calls


class TestResolveDeliveryClearance:
    def test_sends_one_item_scoped_read_with_the_flow_and_workflow(self, monkeypatch):
        dispatch, calls = _recorder(
            {"merge_only": False, "resolved_flow": "acme-prod", "blocked_reason": ""}
        )
        monkeypatch.setattr(clearance, "call_dispatcher", dispatch)

        result = clearance.resolve_delivery_clearance(
            public_ref="YOK-7", deploy_flow="acme-prod", workflow_id="dash"
        )

        assert result == clearance.DeliveryClearance(
            merge_only=False, resolved_flow="acme-prod"
        )
        [call] = calls
        assert call["function_id"] == "done_transition.delivery_clearance"
        assert call["target"].kind == "item"
        assert call["target"].public_ref == "YOK-7"
        assert call["payload"] == {"workflow_id": "dash", "deploy_flow": "acme-prod"}

    def test_never_asks_the_org_admin_reads(self, monkeypatch):
        dispatch, calls = _recorder({"merge_only": True, "resolved_flow": ""})
        monkeypatch.setattr(clearance, "call_dispatcher", dispatch)

        clearance.resolve_delivery_clearance(
            public_ref="YOK-7", deploy_flow="", workflow_id="dash"
        )

        assert {c["function_id"] for c in calls} == {
            "done_transition.delivery_clearance"
        }

    def test_blocked_reason_passes_through_unchanged(self, monkeypatch):
        reason = "deployment_flow 'typo' is not a registered deployment flow."
        dispatch, _ = _recorder(
            {"merge_only": False, "resolved_flow": "typo", "blocked_reason": reason}
        )
        monkeypatch.setattr(clearance, "call_dispatcher", dispatch)

        result = clearance.resolve_delivery_clearance(
            public_ref="YOK-7", deploy_flow="typo", workflow_id="dash"
        )

        assert result.merge_only is False
        assert result.blocked_reason == reason

    def test_a_refused_read_raises_rather_than_reading_as_merge_only(
        self, monkeypatch
    ):
        dispatch, _ = _recorder(success=False, message="permission denied")
        monkeypatch.setattr(clearance, "call_dispatcher", dispatch)

        with pytest.raises(
            RuntimeError,
            match="done_transition.delivery_clearance read failed: permission denied",
        ):
            clearance.resolve_delivery_clearance(
                public_ref="YOK-7", deploy_flow="", workflow_id="dash"
            )

    def test_a_response_missing_merge_only_raises(self, monkeypatch):
        """A malformed answer is not the same fact as a merge-only flow."""
        dispatch, _ = _recorder({"resolved_flow": "acme-prod"})
        monkeypatch.setattr(clearance, "call_dispatcher", dispatch)

        with pytest.raises(RuntimeError, match="named no 'merge_only' field"):
            clearance.resolve_delivery_clearance(
                public_ref="YOK-7", deploy_flow="acme-prod", workflow_id="dash"
            )

    def test_a_missing_public_ref_raises_a_named_refusal(self, monkeypatch):
        monkeypatch.setattr(
            clearance, "call_dispatcher",
            lambda **_: pytest.fail("no read without an item"),
        )
        with pytest.raises(RuntimeError, match="needs the item's public ref"):
            clearance.resolve_delivery_clearance(
                public_ref="", deploy_flow="", workflow_id="dash"
            )


class TestResolveDefaultDeliveryFlow:
    def test_returns_the_servers_resolved_default(self, monkeypatch):
        dispatch, calls = _recorder(
            {"merge_only": False, "resolved_flow": "ext-default", "blocked_reason": ""}
        )
        monkeypatch.setattr(clearance, "call_dispatcher", dispatch)

        assert (
            clearance.resolve_default_delivery_flow(
                public_ref="EXT-3", workflow_id="dash"
            )
            == "ext-default"
        )
        assert calls[0]["payload"] == {"workflow_id": "dash", "deploy_flow": ""}

    def test_an_unregistered_default_is_still_returned_for_the_guard_to_name(
        self, monkeypatch
    ):
        dispatch, _ = _recorder(
            {"merge_only": False, "resolved_flow": "ghost",
             "blocked_reason": "deployment_flow 'ghost' is not a registered deployment flow."}
        )
        monkeypatch.setattr(clearance, "call_dispatcher", dispatch)

        assert (
            clearance.resolve_default_delivery_flow(public_ref="EXT-3", workflow_id="dash")
            == "ghost"
        )

    def test_no_workflow_id_resolves_empty_without_a_read(self, monkeypatch):
        monkeypatch.setattr(
            clearance, "call_dispatcher", lambda **_: pytest.fail("no read needed"),
        )
        assert (
            clearance.resolve_default_delivery_flow(public_ref="EXT-3", workflow_id="")
            == ""
        )

    def test_relay_failure_raises_rather_than_reading_as_no_config(self, monkeypatch):
        dispatch, _ = _recorder(success=False, message="unavailable")
        monkeypatch.setattr(clearance, "call_dispatcher", dispatch)
        with pytest.raises(RuntimeError, match="unavailable"):
            clearance.resolve_default_delivery_flow(public_ref="YOK-3", workflow_id="dash")
