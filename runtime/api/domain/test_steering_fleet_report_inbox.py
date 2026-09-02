"""This session's injected-but-unacked Fleet inbox."""

from __future__ import annotations

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.steering_fleet_report_hook_digest import (
    DIGEST_PREAMBLE,
    combined_hook_digest,
)
from yoke_core.domain.steering_fleet_report_compose import CombinedFleetReport
from yoke_core.domain.steering_fleet_report_inbox import (
    UnackedInjectedMessage,
    load_unacked_injected,
    unacked_section_lines,
)
from runtime.api.domain.test_session_message_support import (
    NOW_TEXT,
    message_connection,
    selector,
)

MESSAGE_ID = "11111111-2222-4333-8444-555555555555"


def test_unacked_section_is_absent_when_the_inbox_is_empty() -> None:
    assert unacked_section_lines(()) == []


def test_unacked_section_names_the_ack_command() -> None:
    lines = unacked_section_lines(
        (
            UnackedInjectedMessage(
                message_id=MESSAGE_ID,
                last_injected_at="2026-08-22T15:50:00Z",
                age_seconds=600,
            ),
        )
    )
    joined = "\n".join(lines)
    assert "unacked injected (this session)" in joined
    assert f"yoke messages acknowledge {MESSAGE_ID}" in joined
    assert "10m" in joined


def test_load_unacked_injected_skips_rows_inside_the_grace() -> None:
    conn = message_connection()
    sent = send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=["s1"]),
        body="Ack me.",
    )
    conn.execute(
        "UPDATE session_message_recipients SET state='injected',"
        "injection_count=1,last_injected_at=? WHERE message_id=?",
        ("2026-08-22T15:56:00Z", sent["message_id"]),
    )
    conn.commit()
    found = load_unacked_injected(
        conn, session_id="s1", now=NOW_TEXT, grace_seconds=300
    )
    assert found == ()


def test_load_unacked_injected_lists_rows_past_the_grace() -> None:
    conn = message_connection()
    sent = send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=["s1"]),
        body="Ack me.",
    )
    conn.execute(
        "UPDATE session_message_recipients SET state='injected',"
        "injection_count=1,last_injected_at=? WHERE message_id=?",
        ("2026-08-22T15:50:00Z", sent["message_id"]),
    )
    conn.commit()
    found = load_unacked_injected(
        conn, session_id="s1", now=NOW_TEXT, grace_seconds=300
    )
    assert len(found) == 1
    assert found[0].message_id == sent["message_id"]
    assert found[0].age_seconds == 600


def test_hook_digest_carries_the_inbox_and_the_pull_command() -> None:
    combined = CombinedFleetReport(
        composed_at=NOW_TEXT,
        sections=(),
        unacked_injected=(
            UnackedInjectedMessage(
                message_id=MESSAGE_ID,
                last_injected_at="2026-08-22T15:50:00Z",
                age_seconds=600,
            ),
        ),
    )
    body = combined_hook_digest(combined)
    assert DIGEST_PREAMBLE in body
    assert "hook digest" in body
    assert f"yoke messages acknowledge {MESSAGE_ID}" in body
    assert combined.actionable
