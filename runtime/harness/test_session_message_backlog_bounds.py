"""Long-session proof for one-shot, bounded Fleet message injection."""

from __future__ import annotations

import pytest

from yoke_core.domain.session_message_delivery import (
    complete_hook_lease,
    lease_for_hook,
)
from yoke_core.domain.session_message_queries import list_messages
from yoke_core.domain.session_message_service import send_message
from yoke_core.hooks.session_message_delivery_port import (
    LeasedSessionMessage,
    SessionMessageLease,
)
from yoke_core.hooks.session_message_rendering import (
    MAX_FULL_MESSAGES_PER_INJECTION,
    MAX_SESSION_MESSAGE_INJECTION_BYTES,
    render_lease,
)
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


@pytest.fixture(autouse=True)
def _fixed_message_clock(monkeypatch) -> None:
    from yoke_core.domain import session_message_delivery

    monkeypatch.setattr(session_message_delivery, "utc_now", lambda: NOW)


def _rendered_lease(raw: dict) -> SessionMessageLease:
    return SessionMessageLease(
        lease_id=raw["lease_id"],
        messages=tuple(
            LeasedSessionMessage(
                message_id=row["message_id"],
                body=row["body"],
                sender_actor_id=row["sender_actor_id"],
            )
            for row in raw["messages"]
        ),
        remaining_count=raw["remaining_count"],
    )


def test_many_unacknowledged_messages_stay_bounded_across_many_hooks() -> None:
    conn = message_connection()
    for index in range(18):
        send_message(
            conn,
            actor_id=10,
            sender_session_id="s1",
            selector=selector(session_ids=["s1"]),
            body=f"message {index}: " + ("x" * 4_000),
            now=NOW,
        )

    rendered_calls: list[str] = []
    for index in range(20):
        event = "PreToolUse" if index % 2 == 0 else "PostToolUse"
        raw = lease_for_hook(conn, session_id="s1", hook_event=event, limit=10)
        if raw is None:
            rendered_calls.append("")
            continue
        rendered, _token = render_lease(
            _rendered_lease(raw),
            session_id="s1",
        )
        rendered_calls.append(rendered)
        complete_hook_lease(
            conn,
            lease_id=raw["lease_id"],
            injected=True,
            result="injected",
        )

    nonempty = [text for text in rendered_calls if text]
    assert len(nonempty) == 2
    assert all(
        len(text.encode("utf-8")) <= MAX_SESSION_MESSAGE_INJECTION_BYTES
        for text in nonempty
    )
    assert all(
        text.count("--- BEGIN YOKE SESSION MESSAGE ") <= MAX_FULL_MESSAGES_PER_INJECTION
        for text in nonempty
    )
    assert "15 additional unacknowledged session message(s)" in nonempty[0]
    assert "--state unacknowledged" in nonempty[0]
    receipts = conn.execute(
        "SELECT state,injection_count FROM session_message_recipients"
    ).fetchall()
    assert {tuple(row) for row in receipts} == {("injected", 1)}
    assert (
        len(
            list_messages(
                conn,
                actor_id=10,
                caller_session_id="s1",
                state="unacknowledged",
                limit=50,
            )
        )
        == 18
    )
