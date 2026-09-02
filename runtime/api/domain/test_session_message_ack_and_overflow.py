"""Recipient ack teaching and inline-overflow lease settlement."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_message_delivery import (
    complete_hook_lease,
    lease_for_hook,
)
from yoke_core.domain.session_message_queries import get_message, list_messages
from yoke_core.domain.session_message_service import send_message
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


@pytest.fixture(autouse=True)
def _fixed_delivery_clock(monkeypatch) -> None:
    from yoke_core.domain import session_message_delivery

    monkeypatch.setattr(session_message_delivery, "utc_now", lambda: NOW)


def _send(conn, *, session_id: str = "s1"):
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=[session_id]),
        body="Act on this.",
        now=NOW,
    )


def test_get_and_list_print_the_ack_command_for_the_recipient() -> None:
    conn = message_connection()
    sent = _send(conn)
    message_id = sent["message_id"]
    command = f"yoke messages acknowledge {message_id}"
    details = get_message(conn, message_id=message_id, actor_id=10, session_id="s1")
    assert details["acknowledgement_command"] == command
    listed = list_messages(conn, actor_id=10, caller_session_id="s1", limit=10)
    assert listed[0]["acknowledgement_command"] == command
    sender = get_message(conn, message_id=message_id, actor_id=10, session_id="s2")
    assert "acknowledgement_command" not in sender


def test_inline_overflow_releases_the_lease_and_leaves_the_receipt_pending() -> None:
    conn = message_connection()
    _send(conn)
    lease = lease_for_hook(conn, session_id="s1", hook_event="PreToolUse", limit=10)
    assert lease
    complete_hook_lease(
        conn,
        lease_id=lease["lease_id"],
        injected=False,
        result="inline_overflow",
    )
    receipt = conn.execute(
        "SELECT state,injection_count,injection_lease_id "
        "FROM session_message_recipients"
    ).fetchone()
    assert tuple(receipt) == ("pending", 0, None)
    result = conn.execute("SELECT result_code FROM session_message_attempts").fetchone()
    assert result["result_code"] == "inline_overflow"
