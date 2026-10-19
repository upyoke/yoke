"""Registered Inbox function metadata and browser actor guard."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import _register_inbox, inbox_decisions
from yoke_core.domain.handlers.inbox_decision_models import (
    DecisionRoleAuthority,
)


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
        "machine_authorization.get",
        "machine_authorization.resolve",
        "machine_authorization.pending",
        "decision_requests.get",
        "inbox.list",
        "decision_requests.create",
        "decision_requests.resolve",
        "decision_requests.withdraw",
        "decision_requests.dispose_ended",
    ]
    live_ids = {
        "machine_authorization.pending",
        "machine_authorization.get",
        "machine_authorization.resolve",
        "decision_requests.get",
    }
    for args, metadata in registry.rows:
        assert metadata["adapter_status"] == (
            "live" if args[0] in live_ids else "internal"
        )
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


def test_inbox_list_excludes_retired_machine_requests(monkeypatch):
    from yoke_core.domain import db_helpers, inbox_read

    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(db_helpers, "connect", Connection)
    monkeypatch.setattr(
        inbox_read,
        "dispose_ended_decision_requests",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        inbox_read,
        "settle_operator_wake_notices",
        lambda *_args, **_kwargs: 0,
    )
    monkeypatch.setattr(
        inbox_read,
        "pending_requests_for_actor",
        lambda *_args, **_kwargs: [
            {"kind": "machine_approval"},
            {"kind": "qa_needs_review"},
        ],
    )
    monkeypatch.setattr(
        inbox_read,
        "recently_decided_requests_for_actor",
        lambda *_args, **_kwargs: [
            {"kind": "machine_approval"},
            {"kind": "deployment_stage_approval"},
        ],
    )
    monkeypatch.setattr(
        inbox_read,
        "inbox_actor_messages",
        lambda *_args, **_kwargs: {"messages": [], "pending_count": 0},
    )

    outcome = inbox_decisions.handle_inbox_list(
        FunctionCallRequest(
            function="inbox.list",
            actor=ActorContext(actor_id="2", session_id="browser"),
            target=TargetRef(kind="global"),
        )
    )

    assert outcome.primary_success is True
    # Both pending and settled retired rows stay outside current Inbox work.
    assert outcome.result_payload["needs_decision"] == [
        {"kind": "qa_needs_review"},
        {"kind": "deployment_stage_approval"},
    ]
    assert "machine_approvals" not in outcome.result_payload
    assert outcome.result_payload["messages"] == []
    assert outcome.result_payload["pending_actor_message_count"] == 0
