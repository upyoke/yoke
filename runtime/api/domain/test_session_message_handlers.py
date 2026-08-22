"""Focused registered handler boundaries for session messages."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.handlers import session_messages
from yoke_core.domain.handlers import session_messages_receipts
from yoke_core.domain.session_message_service import send_message
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


def _request(
    function: str,
    payload: dict,
    *,
    actor_id: str | None = "10",
    session_id: str = "s1",
    target_kind: str = "global",
) -> FunctionCallRequest:
    return FunctionCallRequest.model_validate(
        {
            "function": function,
            "actor": {"actor_id": actor_id, "session_id": session_id},
            "target": {"kind": target_kind},
            "payload": payload,
        }
    )


def test_preview_handler_returns_contract_payload(monkeypatch) -> None:
    conn = message_connection()
    monkeypatch.setattr(session_messages, "open_connection", lambda: conn)
    outcome = session_messages.handle_message_preview(
        _request(
            "session_control.message.preview",
            {"selector": {"session_ids": ["s1"]}},
        )
    )
    assert outcome.primary_success is True
    assert outcome.result_payload["recipient_count"] == 1
    assert outcome.result_payload["recipients"][0]["session_id"] == "s1"


def test_send_handler_returns_message_and_dedupe_shape(monkeypatch) -> None:
    conn = message_connection()
    monkeypatch.setattr(session_messages, "open_connection", lambda: conn)
    outcome = session_messages.handle_message_send(
        _request(
            "session_control.message.send",
            {
                "selector": {"session_ids": ["s1"]},
                "body": "Handler body",
                "idempotency_key": "handler-key",
            },
        )
    )
    assert outcome.primary_success is True
    assert outcome.result_payload["recipient_count"] == 1
    assert outcome.result_payload["deduplicated"] is False
    assert outcome.result_payload["message_id"]


def test_list_and_get_handlers_use_stable_envelopes(monkeypatch) -> None:
    conn = message_connection()
    message_id = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s1"]),
        body="Listed",
        now=NOW,
    )["message_id"]
    monkeypatch.setattr(session_messages, "open_connection", lambda: conn)
    listed = session_messages.handle_message_list(
        _request("session_control.message.list", {})
    )
    assert listed.result_payload["count"] == 1
    assert listed.result_payload["messages"][0]["message_id"] == message_id

    conn = message_connection()
    message_id = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s1"]),
        body="Fetched",
        now=NOW,
    )["message_id"]
    monkeypatch.setattr(session_messages, "open_connection", lambda: conn)
    fetched = session_messages.handle_message_get(
        _request("session_control.message.get", {"message_id": message_id})
    )
    assert fetched.result_payload["message"]["body"] == "Fetched"


def test_handler_refuses_non_global_target_before_opening_connection() -> None:
    outcome = session_messages.handle_message_preview(
        _request(
            "session_control.message.preview",
            {"selector": {"session_ids": ["s1"]}},
            target_kind="item",
        )
    )
    assert outcome.primary_success is False
    assert outcome.error and outcome.error.code == "target_invalid"
    assert outcome.error.jsonpath == "$.target.kind"


def test_handler_requires_dispatcher_bound_numeric_actor(monkeypatch) -> None:
    conn = message_connection()
    monkeypatch.setattr(session_messages, "open_connection", lambda: conn)
    outcome = session_messages.handle_message_preview(
        _request(
            "session_control.message.preview",
            {"selector": {"session_ids": ["s1"]}},
            actor_id=None,
        )
    )
    assert outcome.primary_success is False
    assert outcome.error and outcome.error.code == "actor_required"


def test_acknowledge_handler_binds_recipient_to_actor_session(monkeypatch) -> None:
    conn = message_connection()
    message_id = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s1"]),
        body="Pending",
        now=NOW,
    )["message_id"]
    monkeypatch.setattr(session_messages_receipts, "open_connection", lambda: conn)
    outcome = session_messages_receipts.handle_message_acknowledge(
        _request(
            "session_control.message.acknowledge",
            {"message_id": message_id},
            session_id="s2",
        )
    )
    assert outcome.primary_success is False
    assert outcome.error and outcome.error.code == "acknowledge_self_only"


def test_internal_lease_handler_is_self_only() -> None:
    outcome = session_messages_receipts.handle_message_lease(
        _request(
            "session_control.message.lease",
            {"session_id": "s2", "hook_event": "Stop", "limit": 10},
            session_id="s1",
        )
    )
    assert outcome.primary_success is False
    assert outcome.error and outcome.error.code == "lease_self_only"


def test_invalid_payload_preserves_payload_invalid_outcome() -> None:
    outcome = session_messages.handle_message_send(
        _request("session_control.message.send", {"body": "missing selector"})
    )
    assert outcome.primary_success is False
    assert outcome.error and outcome.error.code == "payload_invalid"
