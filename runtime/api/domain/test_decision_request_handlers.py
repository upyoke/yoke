"""Registered Inbox function metadata and browser actor guard."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import _register_inbox, inbox_decisions


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


def test_browser_actions_fail_closed_without_a_bound_actor():
    outcome = inbox_decisions.handle_inbox_list(FunctionCallRequest(
        function="inbox.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
    ))
    assert outcome.primary_success is False
    assert outcome.error.code == "actor_required"
