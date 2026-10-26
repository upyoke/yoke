"""A re-presented message reads as a reminder: excerpt plus ack command."""

from __future__ import annotations

from yoke_contracts.hook_context_compose import delivered_message_ids
from yoke_core.hooks.session_message_delivery_port import (
    LeasedSessionMessage,
    SessionMessageLease,
)
from yoke_core.hooks.session_message_rendering import (
    REMINDER_EXCERPT_CHARS,
    render_lease,
)


MESSAGE_ID = "11111111-2222-4333-8444-555555555555"
LONG_BODY = "Re-run the merge watcher. " * 60


def _render(message: LeasedSessionMessage) -> tuple[str, str]:
    return render_lease(
        SessionMessageLease(lease_id="lease-1", messages=(message,)),
        session_id="s1",
    )


def test_a_reminder_shows_an_excerpt_and_the_acknowledgement() -> None:
    rendered, token = _render(
        LeasedSessionMessage(
            message_id=MESSAGE_ID, body=LONG_BODY, sender_actor_id=1, shown_count=2
        )
    )

    assert "Reminder: shown 2 time(s) and still unacknowledged." in rendered
    assert LONG_BODY.strip() not in rendered
    assert LONG_BODY[:40] in rendered
    assert f"read the full body with `yoke messages get {MESSAGE_ID}`" in rendered
    assert [line.split()[4:] for line in rendered.splitlines()
            if line.startswith("Acknowledge:")] == [[MESSAGE_ID]]
    assert len(rendered) < REMINDER_EXCERPT_CHARS + 800
    # Settlement still finds the message, so the reminder backs off.
    assert delivered_message_ids(rendered, token) == {MESSAGE_ID}


def test_a_first_delivery_carries_the_whole_body_and_no_reminder() -> None:
    rendered, _token = _render(
        LeasedSessionMessage(message_id=MESSAGE_ID, body=LONG_BODY, sender_actor_id=1)
    )

    assert "Reminder:" not in rendered
    assert "Excerpt only" not in rendered
    assert rendered.count("Re-run the merge watcher.") == 60
