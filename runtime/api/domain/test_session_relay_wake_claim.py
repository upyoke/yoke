"""Atomic native-wake claim coverage."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_relay_wake_claim import claim_wake_attempt
from runtime.api.domain.test_session_message_support import (
    NATIVE_WAKE_SESSION_ID,
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)


def test_stale_candidate_cannot_open_a_duplicate_native_wake_attempt() -> None:
    conn = message_connection()
    message_id = send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Durable body never passed to native wake.",
        now=NOW,
    )["message_id"]
    conn.execute(
        "UPDATE harness_sessions SET native_thread_id=?,ended_at=? WHERE session_id=?",
        ("codex-thread-s4", NOW_TEXT, NATIVE_WAKE_SESSION_ID),
    )
    conn.commit()
    candidate = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11))[0]
    assert candidate["native_thread_id"] == "codex-thread-s4"

    first = claim_wake_attempt(conn, candidate=candidate, now="2026-08-22T16:11:00Z")
    assert first is not None
    conn.commit()
    assert (
        claim_wake_attempt(conn, candidate=candidate, now="2026-08-22T16:11:01Z")
        is None
    )

    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients "
            "WHERE message_id=?",
            (message_id,),
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM session_message_attempts WHERE completed_at IS NULL"
        ).fetchone()[0]
        == 1
    )
    assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=12)) == []


def test_concurrent_relays_cannot_claim_the_same_recipient(tmp_path) -> None:
    path = tmp_path / "wake-cas.sqlite"
    seed = message_connection(str(path))
    send_message(
        seed,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="One wake only.",
        now=NOW,
    )
    seed.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id=?",
        (NOW_TEXT, NATIVE_WAKE_SESSION_ID),
    )
    seed.commit()
    candidate = wake_eligible_recipients(seed, now=NOW + timedelta(minutes=11))[0]
    seed.close()

    def claim_once() -> bool:
        conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            claim = claim_wake_attempt(
                conn, candidate=candidate, now="2026-08-22T16:11:00Z"
            )
            if claim is not None:
                conn.commit()
            return claim is not None
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda _index: claim_once(), range(2)))

    assert sorted(claimed) == [False, True]
    check = sqlite3.connect(path)
    assert (
        check.execute("SELECT COUNT(*) FROM session_message_attempts").fetchone()[0]
        == 1
    )
    check.close()


def test_new_liveness_observation_invalidates_a_selected_candidate() -> None:
    conn = message_connection()
    send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Do not wake an active prompt.",
        now=NOW,
    )
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id=?",
        (NOW_TEXT, NATIVE_WAKE_SESSION_ID),
    )
    conn.commit()
    candidate = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11))[0]
    conn.execute(
        "UPDATE harness_sessions SET ended_at=NULL,last_heartbeat=?,"
        "last_tool_call_at=? WHERE session_id=?",
        (
            "2026-08-22T16:11:00Z",
            "2026-08-22T16:11:00Z",
            NATIVE_WAKE_SESSION_ID,
        ),
    )
    conn.commit()

    claim = claim_wake_attempt(conn, candidate=candidate, now="2026-08-22T16:11:00Z")

    assert claim is None
    assert (
        conn.execute("SELECT COUNT(*) FROM session_message_attempts").fetchone()[0] == 0
    )


def test_idle_wake_skips_when_a_heartbeat_landed_after_send() -> None:
    conn = message_connection()
    send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Injection already has this session.",
        now=NOW,
    )
    conn.execute(
        "UPDATE harness_sessions SET ended_at=?,last_heartbeat=? WHERE session_id=?",
        (NOW_TEXT, "2026-08-22T16:00:01Z", NATIVE_WAKE_SESSION_ID),
    )
    conn.commit()

    assert wake_eligible_recipients(conn, now=NOW + timedelta(seconds=30)) == []


def test_idle_wake_fires_when_no_activity_landed_after_send() -> None:
    conn = message_connection()
    send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Wake the truly quiet session.",
        now=NOW,
    )
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id=?",
        (NOW_TEXT, NATIVE_WAKE_SESSION_ID),
    )
    conn.commit()
    candidates = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=4))
    assert len(candidates) == 1
    claim = claim_wake_attempt(
        conn, candidate=candidates[0], now="2026-08-22T16:04:00Z"
    )
    assert claim is not None


def test_idle_wake_claim_skips_when_injection_landed_after_send() -> None:
    conn = message_connection()
    send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Do not resume after hook injection.",
        now=NOW,
    )
    conn.execute(
        "UPDATE harness_sessions SET ended_at=? WHERE session_id=?",
        (NOW_TEXT, NATIVE_WAKE_SESSION_ID),
    )
    conn.commit()
    candidate = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=4))[0]
    conn.execute(
        "UPDATE session_message_recipients SET last_injected_at=?",
        ("2026-08-22T16:00:01Z",),
    )
    conn.commit()
    assert (
        claim_wake_attempt(conn, candidate=candidate, now="2026-08-22T16:04:00Z")
        is None
    )
