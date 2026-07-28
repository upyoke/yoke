"""Registered Inbox function metadata and browser actor guard."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import _register_inbox, inbox_decisions
from yoke_core.domain.handlers.inbox_decision_models import DecisionRoleAuthority


def test_handler_module_preserves_public_authority_model_export():
    assert inbox_decisions.DecisionRoleAuthority is DecisionRoleAuthority


def test_registration_leaf_declares_every_engine_action():
    class Registry:
        def __init__(self):
            self.rows = []

        def register(self, *args, **kwargs):
            self.rows.append((args, kwargs))

    registry = Registry()
    _register_inbox.register(registry)
    assert [row[0][0] for row in registry.rows] == [
        "inbox.list",
        "decision_requests.create",
        "decision_requests.resolve",
        "decision_requests.withdraw",
        "notifications.read",
        "notifications.read_all",
    ]
    assert all(row[1]["adapter_status"] == "internal" for row in registry.rows)
    read_all = next(
        row for row in registry.rows if row[0][0] == "notifications.read_all"
    )
    assert read_all[0][2] is inbox_decisions.NotificationsReadAllRequest
    assert "project_scope_exact" in read_all[1]["guardrails"]
    withdraw = next(
        row for row in registry.rows if row[0][0] == "decision_requests.withdraw"
    )
    assert withdraw[1]["guardrails"] == [
        "actor_required",
        "live_authority_union",
        "subject_ended",
        "never_silent_expiry",
    ]


def test_browser_actions_fail_closed_without_a_bound_actor():
    outcome = inbox_decisions.handle_inbox_list(
        FunctionCallRequest(
            function="inbox.list",
            actor=ActorContext(actor_id=None, session_id=""),
            target=TargetRef(kind="global"),
        )
    )
    assert outcome.primary_success is False
    assert outcome.error.code == "actor_required"


def test_generic_create_cannot_mint_lifecycle_approvals():
    outcome = inbox_decisions.handle_decision_create(
        FunctionCallRequest(
            function="decision_requests.create",
            actor=ActorContext(actor_id="1", session_id="browser"),
            target=TargetRef(kind="global"),
            payload={
                "kind": "lifecycle_transition_approval",
                "subject_type": "item_transition",
                "subject_key": "42:done",
                "project_id": 1,
                "named_actor_ids": [1],
            },
        )
    )
    assert outcome.primary_success is False
    assert outcome.error.jsonpath == "$.payload"
