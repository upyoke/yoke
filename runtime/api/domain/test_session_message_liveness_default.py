"""Bulk recipient anchors resolve against active sessions unless widened."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)
from yoke_core.domain.session_message_selectors import resolve_recipients
from yoke_core.domain.session_message_service import preview_message, send_message
from yoke_core.domain.session_message_types import SessionMessageError

ENDED = "s-ended"
STALE = "s-stale"
#: Far enough behind NOW that every executor's stale window has elapsed.
LONG_AGO = "2026-08-01T00:00:00Z"


def _connection_with_inactive_sessions():
    """Seed one ended and one stale session beside the active fixture rows."""
    conn = message_connection()
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id,project_id,executor,executor_surface,executor_version,"
        "machine_id,execution_lane,last_heartbeat,last_tool_call_at,offered_at,"
        "ended_at) VALUES "
        f"('{ENDED}',1,'codex','codex-desktop','26.814.41407','m1','direct',"
        f"'{NOW_TEXT}','{NOW_TEXT}','{NOW_TEXT}','{NOW_TEXT}'),"
        f"('{STALE}',1,'codex','codex-desktop','26.814.41407','m1','direct',"
        f"'{LONG_AGO}','{LONG_AGO}','{LONG_AGO}',NULL)"
    )
    conn.commit()
    return conn


def _resolved(conn, **values) -> list[str]:
    return [
        row.session_id for row in resolve_recipients(conn, selector(**values), now=NOW)
    ]


def test_project_send_skips_ended_and_stale_sessions_by_default() -> None:
    conn = _connection_with_inactive_sessions()
    try:
        reached = _resolved(conn, projects=["alpha"])

        assert ENDED not in reached
        assert STALE not in reached
        assert reached == ["s1", "s2", "s4"]
    finally:
        conn.close()


def test_universe_skips_ended_sessions_by_default() -> None:
    conn = _connection_with_inactive_sessions()
    try:
        assert ENDED not in _resolved(conn, universe=True)
    finally:
        conn.close()


def test_liveness_all_restores_every_state() -> None:
    conn = _connection_with_inactive_sessions()
    try:
        reached = _resolved(conn, projects=["alpha"], liveness=["all"])

        assert ENDED in reached
        assert STALE in reached
    finally:
        conn.close()


def test_explicit_liveness_widens_to_exactly_what_it_names() -> None:
    conn = _connection_with_inactive_sessions()
    try:
        assert _resolved(conn, projects=["alpha"], liveness=["ended"]) == [ENDED]
        assert _resolved(conn, projects=["alpha"], liveness=["stale"]) == [STALE]
    finally:
        conn.close()


def test_an_exact_session_anchor_still_reaches_an_ended_session() -> None:
    conn = _connection_with_inactive_sessions()
    try:
        assert _resolved(conn, session_ids=[ENDED]) == [ENDED]
    finally:
        conn.close()


def test_a_named_session_survives_a_bulk_anchor_in_the_same_selector() -> None:
    """The default narrows the population, never a deliberately named target."""
    conn = _connection_with_inactive_sessions()
    try:
        reached = _resolved(conn, session_ids=[ENDED], projects=["alpha"])

        assert ENDED in reached
        assert STALE not in reached
    finally:
        conn.close()


def test_an_item_anchor_reaching_an_ended_holder_is_unaffected() -> None:
    conn = _connection_with_inactive_sessions()
    try:
        conn.execute("UPDATE work_claims SET session_id=? WHERE id=1", (ENDED,))
        conn.commit()

        assert _resolved(conn, public_refs=["ALP-1"]) == [ENDED]
    finally:
        conn.close()


def test_preview_names_the_applied_liveness_filter() -> None:
    conn = _connection_with_inactive_sessions()
    try:
        default = preview_message(
            conn, actor_id=10, selector=selector(projects=["alpha"]), now=NOW
        )
        widened = preview_message(
            conn,
            actor_id=10,
            selector=selector(projects=["alpha"], liveness=["all"]),
            now=NOW,
        )

        assert default["applied_liveness"] == ["active"]
        assert widened["applied_liveness"] == ["active", "stale", "ended"]
    finally:
        conn.close()


def test_an_exact_anchor_preview_names_every_state() -> None:
    conn = _connection_with_inactive_sessions()
    try:
        preview = preview_message(
            conn, actor_id=10, selector=selector(session_ids=["s1"]), now=NOW
        )

        assert preview["applied_liveness"] == ["active", "stale", "ended"]
    finally:
        conn.close()


def test_the_stored_snapshot_names_what_the_sender_resolved_against() -> None:
    conn = _connection_with_inactive_sessions()
    try:
        result = send_message(
            conn,
            actor_id=10,
            sender_session_id="s1",
            selector=selector(projects=["alpha"]),
            body="Pause the fleet.",
            now=NOW,
        )
        message = conn.execute(
            "SELECT selector_snapshot FROM session_messages WHERE message_id=?",
            (result["message_id"],),
        ).fetchone()

        snapshot = json.loads(message["selector_snapshot"])
        assert snapshot["applied_liveness"] == ["active"]
        assert snapshot["projects"] == ["alpha"]
        assert ENDED not in [row["session_id"] for row in result["recipients"]]
    finally:
        conn.close()


def test_a_bulk_selector_that_reaches_nobody_active_refuses_the_send() -> None:
    conn = _connection_with_inactive_sessions()
    try:
        conn.execute(
            "UPDATE harness_sessions SET ended_at=? WHERE session_id IN "
            "('s1','s2','s4')",
            (NOW_TEXT,),
        )
        conn.commit()

        with pytest.raises(SessionMessageError) as refusal:
            preview_message(
                conn, actor_id=10, selector=selector(projects=["alpha"]), now=NOW
            )
        assert refusal.value.code == "zero_recipients"
    finally:
        conn.close()


@pytest.mark.parametrize("value", ["awake", "ALL", "done", ""])
def test_an_unknown_liveness_state_is_refused_at_the_contract(value: str) -> None:
    with pytest.raises(ValidationError, match="unknown liveness states"):
        selector(projects=["alpha"], liveness=[value])
