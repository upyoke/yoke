"""Transactional send, receipt, visibility, and idempotency tests."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import pytest

from yoke_core.domain.session_message_delivery import (
    complete_hook_lease,
    lease_for_hook,
)
from yoke_core.domain.session_message_service import (
    acknowledge_message,
    cancel_message,
    get_message,
    list_messages,
    preview_message,
    send_message,
)
from yoke_core.domain.session_message_types import SessionMessageError, parse_timestamp
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


@pytest.fixture(autouse=True)
def _fixed_delivery_clock(monkeypatch) -> None:
    from yoke_core.domain import session_message_delivery

    monkeypatch.setattr(session_message_delivery, "utc_now", lambda: NOW)


def _send(conn, *, target=None, body="Act on this.", key=None, actor_id=10):
    return send_message(
        conn,
        actor_id=actor_id,
        sender_session_id="s1" if actor_id == 10 else None,
        selector=target or selector(session_ids=["s1"]),
        body=body,
        idempotency_key=key,
        now=NOW,
    )


def test_send_stores_body_hash_selector_and_immutable_recipient_snapshot() -> None:
    conn = message_connection()
    result = _send(
        conn,
        target=selector(session_ids=["s1"], item_refs=["ALP-1"]),
        body="Inspect the failing test.",
    )

    message = conn.execute(
        "SELECT * FROM session_messages WHERE message_id=?",
        (result["message_id"],),
    ).fetchone()
    recipient = conn.execute(
        "SELECT * FROM session_message_recipients WHERE message_id=?",
        (result["message_id"],),
    ).fetchone()
    assert (
        message["body_sha256"]
        == hashlib.sha256(b"Inspect the failing test.").hexdigest()
    )
    assert json.loads(message["selector_snapshot"])["session_ids"] == ["s1"]
    assert json.loads(recipient["resolution_evidence"]) == [
        "item:ALP-1",
        "session:s1",
    ]
    routing = json.loads(recipient["routing_snapshot"])
    assert routing["executor_version"] == "26.814.41407"
    assert routing["authorized_project_ids"] == [1]
    assert recipient["state"] == "pending"


def test_sender_idempotency_deduplicates_without_retargeting_claim_changes() -> None:
    conn = message_connection()
    target = selector(item_refs=["ALP-1"])
    first = _send(conn, target=target, key="same-intent")
    conn.execute("UPDATE work_claims SET released_at=? WHERE id=1", (str(NOW),))
    conn.execute(
        "INSERT INTO work_claims "
        "(id,session_id,target_kind,item_id,claimed_at) "
        "VALUES (4,'s2','item',101,?)",
        (str(NOW),),
    )
    conn.commit()

    second = _send(conn, target=target, key="same-intent")

    assert second["message_id"] == first["message_id"]
    assert second["deduplicated"] is True
    assert [row["session_id"] for row in second["recipients"]] == ["s1"]
    assert conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("changed"),
    [
        {"body": "Different body"},
        {"target": selector(session_ids=["s2"])},
    ],
)
def test_idempotency_key_rejects_a_different_intent(changed: dict) -> None:
    conn = message_connection()
    _send(conn, key="fixed")
    with pytest.raises(SessionMessageError) as raised:
        _send(conn, key="fixed", **changed)
    assert raised.value.code == "idempotency_conflict"


def test_send_refuses_empty_oversized_and_unqualified_routes() -> None:
    conn = message_connection()
    with pytest.raises(SessionMessageError) as empty:
        _send(conn, body="")
    assert empty.value.code == "body_empty"

    conn.execute(
        "UPDATE organizations SET settings=? WHERE id=1",
        (json.dumps({"fleet": {"max_body_bytes": 4}}),),
    )
    conn.commit()
    with pytest.raises(SessionMessageError) as oversized:
        _send(conn, body="12345")
    assert oversized.value.code == "body_too_large"

    conn.execute("UPDATE organizations SET settings='{}' WHERE id=1")
    conn.execute(
        "UPDATE harness_sessions SET executor_version=NULL WHERE session_id='s1'"
    )
    conn.commit()
    with pytest.raises(SessionMessageError) as route:
        _send(conn)
    assert route.value.code == "unsupported_route"


def test_universe_send_requires_exact_current_preview() -> None:
    conn = message_connection()
    target = selector(universe=True)
    preview = preview_message(conn, actor_id=12, selector=target, now=NOW)
    with pytest.raises(SessionMessageError) as missing:
        send_message(
            conn,
            actor_id=12,
            sender_session_id=None,
            selector=target,
            body="Broadcast",
            now=NOW,
        )
    assert missing.value.code == "broadcast_confirmation_required"

    sent = send_message(
        conn,
        actor_id=12,
        sender_session_id=None,
        selector=target,
        body="Broadcast",
        supplied_confirmation_token=preview["confirmation_token"],
        now=NOW,
    )
    assert sent["recipient_count"] == 4


def test_confirmed_send_refuses_recipient_drift_after_preview() -> None:
    conn = message_connection()
    target = selector(item_refs=["ALP-1"])
    preview = preview_message(conn, actor_id=10, selector=target, now=NOW)
    assert [row["session_id"] for row in preview["recipients"]] == ["s1"]
    conn.execute("UPDATE work_claims SET released_at=? WHERE id=1", (str(NOW),))
    conn.execute(
        "INSERT INTO work_claims "
        "(id,session_id,target_kind,item_id,claimed_at) "
        "VALUES (4,'s2','item',101,?)",
        (str(NOW),),
    )
    conn.commit()

    with pytest.raises(SessionMessageError) as changed:
        send_message(
            conn,
            actor_id=10,
            sender_session_id=None,
            selector=target,
            body="Act on the confirmed recipient snapshot.",
            supplied_confirmation_token=preview["confirmation_token"],
            now=NOW,
        )

    assert changed.value.code == "recipient_snapshot_changed"
    assert conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 0


def test_get_and_list_visibility_follows_sender_recipient_or_project_read() -> None:
    conn = message_connection()
    message_id = _send(conn)["message_id"]

    assert (
        get_message(conn, message_id=message_id, actor_id=10, session_id="s2")[
            "message_id"
        ]
        == message_id
    )
    assert (
        get_message(conn, message_id=message_id, actor_id=13, session_id="s1")[
            "message_id"
        ]
        == message_id
    )
    assert len(list_messages(conn, actor_id=11, caller_session_id="s2", limit=10)) == 1
    with pytest.raises(SessionMessageError) as denied:
        get_message(conn, message_id=message_id, actor_id=13, session_id="s3")
    assert denied.value.code == "message_forbidden"


def test_sender_or_every_project_admin_cancels_and_receipt_state_is_terminal() -> None:
    conn = message_connection()
    message_id = _send(conn)["message_id"]
    with pytest.raises(SessionMessageError) as denied:
        cancel_message(conn, message_id=message_id, actor_id=13, now=NOW)
    assert denied.value.code == "cancel_forbidden"

    cancelled = cancel_message(conn, message_id=message_id, actor_id=12, now=NOW)
    assert cancelled["cancelled_by_actor_id"] == 12
    assert cancelled["cancellation_reason"] == "cancelled_by_project_admin"
    assert cancelled["recipients"][0]["state"] == "cancelled"
    assert (
        lease_for_hook(conn, session_id="s1", hook_event="PreToolUse", limit=10) is None
    )

    sender_message_id = _send(conn, body="Sender cancellation proof.")["message_id"]
    sender_cancelled = cancel_message(
        conn, message_id=sender_message_id, actor_id=10, now=NOW
    )
    assert sender_cancelled["cancelled_by_actor_id"] == 10
    assert sender_cancelled["cancellation_reason"] == "cancelled_by_sender"


def _wake_after(conn, message_id: str):
    return conn.execute(
        "SELECT wake_after FROM session_message_recipients WHERE message_id=?",
        (message_id,),
    ).fetchone()[0]


def test_default_send_stamps_the_fleet_idle_grace() -> None:
    conn = message_connection()
    result = _send(conn)
    assert parse_timestamp(_wake_after(conn, result["message_id"])) == NOW + timedelta(
        minutes=3
    )


def test_urgent_send_stamps_wake_after_at_send_time() -> None:
    conn = message_connection()
    result = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s1"]),
        body="Act now.",
        now=NOW,
        urgent=True,
    )
    assert parse_timestamp(_wake_after(conn, result["message_id"])) == NOW


def test_wake_after_seconds_overrides_fleet_idle_grace() -> None:
    conn = message_connection()
    result = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s1"]),
        body="Act soon.",
        now=NOW,
        wake_after_seconds=30,
    )
    assert parse_timestamp(_wake_after(conn, result["message_id"])) == NOW + timedelta(
        seconds=30
    )


def test_acknowledgment_is_self_only_and_requires_prior_injection() -> None:
    conn = message_connection()
    message_id = _send(conn)["message_id"]
    with pytest.raises(SessionMessageError) as pending:
        acknowledge_message(conn, message_id=message_id, session_id="s1", now=NOW)
    assert pending.value.code == "invalid_state"
    with pytest.raises(SessionMessageError) as other:
        acknowledge_message(conn, message_id=message_id, session_id="s2", now=NOW)
    assert other.value.code == "acknowledge_self_only"

    lease = lease_for_hook(conn, session_id="s1", hook_event="PreToolUse", limit=10)
    assert lease
    complete_hook_lease(
        conn, lease_id=lease["lease_id"], injected=True, result="injected"
    )
    acknowledged = acknowledge_message(
        conn, message_id=message_id, session_id="s1", now=NOW
    )
    assert acknowledged["recipients"][0]["state"] == "acknowledged"
    assert (
        lease_for_hook(conn, session_id="s1", hook_event="PostToolUse", limit=10)
        is None
    )
