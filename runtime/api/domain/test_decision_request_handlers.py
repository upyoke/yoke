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
    MachineApprovalLifecycleRequest,
)
from yoke_core.domain import machine_approval_requests
from yoke_core.domain.function_authz_product_scopes import PRODUCT_AUTHZ_BY_ID
from yoke_core.domain.function_authz_types import ACTOR_SESSION


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
        "machine_approval.lifecycle.apply",
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
    machine = next(
        row for row in registry.rows if row[0][0] == "machine_approval.lifecycle.apply"
    )
    assert (
        machine[0][1]
        is machine_approval_requests.apply_machine_approval_lifecycle_request
    )
    assert machine[0][2] is MachineApprovalLifecycleRequest
    assert "terminal_replay_idempotent" in machine[1]["guardrails"]
    assert PRODUCT_AUTHZ_BY_ID[machine[0][0]].scope == ACTOR_SESSION


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


def test_inbox_list_excludes_platform_owned_machine_request(monkeypatch):
    from yoke_core.domain import db_helpers, decision_requests, inbox_notifications

    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(db_helpers, "connect", Connection)
    monkeypatch.setattr(
        decision_requests,
        "pending_requests_for_actor",
        lambda *_args, **_kwargs: [
            {"kind": "machine_approval", "blocking": True},
            {"kind": "qa_needs_review", "blocking": True},
        ],
    )
    monkeypatch.setattr(
        inbox_notifications,
        "notification_rows",
        lambda *_args, **_kwargs: [],
    )

    outcome = inbox_decisions.handle_inbox_list(
        FunctionCallRequest(
            function="inbox.list",
            actor=ActorContext(actor_id="2", session_id="browser"),
            target=TargetRef(kind="global"),
        )
    )

    assert outcome.primary_success is True
    assert outcome.result_payload["needs_decision"] == [
        {"kind": "qa_needs_review", "blocking": True}
    ]


def test_machine_lifecycle_handler_preserves_actor_and_timestamps(monkeypatch):
    from yoke_core.domain import db_helpers, external_identities

    class Connection:
        closed = False

        def close(self):
            self.closed = True

    connection = Connection()
    calls = []
    monkeypatch.setattr(db_helpers, "connect", lambda: connection)
    monkeypatch.setattr(external_identities, "default_org_id", lambda _conn: 1)
    monkeypatch.setattr(
        machine_approval_requests,
        "apply_machine_approval_lifecycle",
        lambda _conn, **kwargs: (
            calls.append(kwargs) or ({"id": 7, "status": "pending"}, True, True)
        ),
    )

    outcome = machine_approval_requests.apply_machine_approval_lifecycle_request(
        FunctionCallRequest(
            function="machine_approval.lifecycle.apply",
            actor=ActorContext(actor_id="5", session_id="platform-delivery"),
            target=TargetRef(kind="global"),
            payload={
                "authorization_id": "5b234860-c927-46ab-b19a-9fb36df056aa",
                "state": "pending",
                "occurred_at": "2026-07-28T12:00:00Z",
                "expires_at": "2026-07-28T12:10:00Z",
            },
        )
    )

    assert outcome.primary_success is True
    assert outcome.result_payload["created"] is True
    assert calls[0]["actor_id"] == 5
    assert calls[0]["org_id"] == 1
    assert calls[0]["session_id"] == "platform-delivery"
    assert calls[0]["state"] == "pending"
    assert calls[0]["occurred_at"] == "2026-07-28T12:00:00+00:00"
    assert calls[0]["context"] == {"expires_at": "2026-07-28T12:10:00+00:00"}
    assert connection.closed is True


def test_machine_lifecycle_handler_rejects_unbounded_pending_payload():
    outcome = machine_approval_requests.apply_machine_approval_lifecycle_request(
        FunctionCallRequest(
            function="machine_approval.lifecycle.apply",
            actor=ActorContext(actor_id="5", session_id="platform-delivery"),
            target=TargetRef(kind="global"),
            payload={
                "authorization_id": "5b234860-c927-46ab-b19a-9fb36df056aa",
                "state": "pending",
                "occurred_at": "2026-07-28T12:00:00Z",
            },
        )
    )
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"
