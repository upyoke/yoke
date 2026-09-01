"""Human-recipient fan-out, inbox reads, and acknowledgements."""

from __future__ import annotations

import pytest

from yoke_contracts.session_control.sender_surface import CLI_SENDER_SURFACE
from yoke_core.domain.actor_message_recipients import inbox_actor_messages
from yoke_core.domain.actor_permissions import (
    ROLE_OPERATOR,
    ROLE_VIEWER,
    grant_actor_org_role,
)
from yoke_core.domain.session_message_service import (
    acknowledge_actor_message,
    preview_message,
    send_message,
)
from yoke_core.domain.session_message_types import SessionMessageError
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


@pytest.fixture(autouse=True)
def _fixed_actor_inbox_clock(monkeypatch) -> None:
    from yoke_core.domain import actor_message_recipients

    monkeypatch.setattr(actor_message_recipients, "utc_now", lambda: NOW)


def _members():
    conn = message_connection()
    grant_actor_org_role(conn, actor_id=10, org_id=1, role_name=ROLE_OPERATOR)
    grant_actor_org_role(conn, actor_id=11, org_id=1, role_name=ROLE_VIEWER)
    conn.execute(
        "INSERT INTO actor_labels (actor_id,surface,label,created_at) "
        "VALUES (11,'github_label','grace','2026-08-22T12:00:00Z')"
    )
    conn.commit()
    return conn


def test_actor_anchor_unions_with_session_fanout_and_snapshots_once() -> None:
    conn = _members()
    target = selector(actors=["grace"], session_ids=["s1"])

    preview = preview_message(conn, actor_id=10, selector=target, now=NOW)
    sent = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        sender_surface=CLI_SENDER_SURFACE,
        selector=target,
        body="Review the shared change.",
        now=NOW,
    )

    assert preview["recipient_count"] == 2
    assert preview["actor_recipients"] == [
        {
            "actor_id": 11,
            "label": "Grace",
            "kind": "human",
            "resolution": ["actor:grace"],
        }
    ]
    assert sent["recipient_count"] == 2
    assert sent["actor_recipients"][0]["actor_id"] == 11
    details = conn.execute(
        "SELECT sender_surface,selector_snapshot FROM session_messages "
        "WHERE message_id=?",
        (sent["message_id"],),
    ).fetchone()
    assert details["sender_surface"] == "cli"
    assert '"actors":["grace"]' in details["selector_snapshot"]
    assert conn.execute(
        "SELECT COUNT(*) FROM session_message_recipients WHERE message_id=?",
        (sent["message_id"],),
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT state FROM actor_message_recipients WHERE message_id=?",
        (sent["message_id"],),
    ).fetchone()[0] == "pending"


def test_actor_inbox_acknowledgement_is_self_only_and_updates_badge() -> None:
    conn = _members()
    sent = send_message(
        conn,
        actor_id=10,
        sender_session_id=None,
        sender_surface="web_form",
        selector=selector(actors=["11"]),
        body="Please read this message.",
        now=NOW,
    )
    message_id = sent["message_id"]

    inbox = inbox_actor_messages(conn, actor_id=11, include_read=False)
    assert inbox["pending_count"] == 1
    assert inbox["messages"][0]["sender_actor_label"] == "Ada"
    assert inbox["messages"][0]["sender_surface_label"] == "dashboard"
    with pytest.raises(SessionMessageError) as denied:
        acknowledge_actor_message(conn, message_id=message_id, actor_id=12, now=NOW)
    assert denied.value.code == "actor_acknowledge_self_only"
    conn.rollback()

    acknowledged = acknowledge_actor_message(
        conn, message_id=message_id, actor_id=11, now=NOW
    )
    receipt = acknowledged["actor_recipients"][0]
    assert receipt["state"] == "read"
    assert receipt["read_at"]
    assert inbox_actor_messages(conn, actor_id=11, include_read=False) == {
        "messages": [],
        "pending_count": 0,
    }


def test_registered_sender_defaults_to_harness_session_surface() -> None:
    conn = _members()
    message_id = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(actors=["11"]),
        body="Sent from a registered harness session.",
        now=NOW,
    )["message_id"]

    row = conn.execute(
        "SELECT sender_surface FROM session_messages WHERE message_id=?",
        (message_id,),
    ).fetchone()
    assert row[0] == "harness_session"


def test_expired_actor_receipt_cannot_be_acknowledged() -> None:
    conn = _members()
    message_id = send_message(
        conn,
        actor_id=10,
        sender_session_id=None,
        selector=selector(actors=["11"]),
        body="This expires.",
        now=NOW,
    )["message_id"]
    conn.execute(
        "UPDATE session_messages SET expires_at=? WHERE message_id=?",
        (NOW.isoformat(), message_id),
    )
    conn.commit()

    assert inbox_actor_messages(conn, actor_id=11, include_read=False)[
        "pending_count"
    ] == 0
    with pytest.raises(SessionMessageError) as expired:
        acknowledge_actor_message(conn, message_id=message_id, actor_id=11, now=NOW)
    assert expired.value.code == "invalid_state"
    assert conn.execute(
        "SELECT state FROM actor_message_recipients WHERE message_id=?",
        (message_id,),
    ).fetchone()[0] == "expired"
