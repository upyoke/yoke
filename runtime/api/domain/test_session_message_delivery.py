"""Concurrent hook lease, completion, expiry, and wake tests."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

import yoke_core.domain.session_message_delivery as message_delivery
from yoke_core.domain.session_message_delivery import (
    complete_hook_lease,
    expire_due_recipients,
    lease_for_hook,
)
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_turn_posture import stamp_turn_posture
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)


@pytest.fixture(autouse=True)
def _fixed_message_clock(monkeypatch):
    monkeypatch.setattr(message_delivery, "utc_now", lambda: NOW)


def _send(conn, *, body="Persistent instructions.") -> str:
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s1"]),
        body=body,
        now=NOW,
    )["message_id"]


def test_hook_completion_reinjects_until_explicit_acknowledgment() -> None:
    conn = message_connection()
    message_id = _send(conn)

    first = lease_for_hook(conn, session_id="s1", hook_event="Stop", limit=10)
    assert first == {
        "lease_id": first["lease_id"],
        "messages": [
            {
                "message_id": message_id,
                "body": "Persistent instructions.",
                "sender_actor_id": 10,
            }
        ],
    }
    assert (
        complete_hook_lease(
            conn, lease_id=first["lease_id"], injected=True, result="injected"
        )
        == 1
    )
    second = lease_for_hook(conn, session_id="s1", hook_event="PostToolUse", limit=10)
    assert second and second["messages"][0]["message_id"] == message_id
    complete_hook_lease(
        conn, lease_id=second["lease_id"], injected=True, result="injected"
    )

    receipt = conn.execute(
        "SELECT state,injection_count FROM session_message_recipients"
    ).fetchone()
    assert tuple(receipt) == ("injected", 2)
    assert (
        conn.execute("SELECT COUNT(*) FROM session_message_attempts").fetchone()[0] == 2
    )


def test_sibling_denial_releases_without_marking_injected() -> None:
    conn = message_connection()
    _send(conn)
    first = lease_for_hook(conn, session_id="s1", hook_event="PreToolUse", limit=10)
    assert first
    conn.execute(
        "UPDATE session_message_recipients "
        "SET injection_lease_expires_at='2099-01-01T00:00:00Z'"
    )
    conn.commit()
    assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11)) == []
    complete_hook_lease(
        conn,
        lease_id=first["lease_id"],
        injected=False,
        result="dropped_by_sibling_denial",
    )
    receipt = conn.execute(
        "SELECT state,injection_count,injection_lease_id "
        "FROM session_message_recipients"
    ).fetchone()
    assert tuple(receipt) == ("pending", 0, None)
    result = conn.execute(
        "SELECT result_code,evidence FROM session_message_attempts"
    ).fetchone()
    assert result["result_code"] == "dropped_by_sibling_denial"
    assert "Persistent instructions" not in result["evidence"]
    assert lease_for_hook(conn, session_id="s1", hook_event="PostToolUse", limit=10)


def test_hook_lease_refuses_non_model_visible_event() -> None:
    conn = message_connection()
    _send(conn)
    assert (
        lease_for_hook(conn, session_id="s1", hook_event="Notification", limit=10)
        is None
    )
    assert (
        conn.execute("SELECT COUNT(*) FROM session_message_attempts").fetchone()[0] == 0
    )


def test_concurrent_hook_leases_exclude_the_same_receipt(tmp_path) -> None:
    path = tmp_path / "messages.sqlite"
    seed = message_connection(str(path))
    _send(seed)
    seed.close()

    def lease_once():
        conn = sqlite3.connect(str(path), timeout=5, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            return lease_for_hook(conn, session_id="s1", hook_event="Stop", limit=10)
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        leases = list(pool.map(lambda _index: lease_once(), range(2)))
    present = [lease for lease in leases if lease is not None]
    assert len(present) == 1
    assert len(present[0]["messages"]) == 1


def test_expired_hook_lease_closes_old_attempt_before_releasing_again() -> None:
    conn = message_connection()
    _send(conn)
    first = lease_for_hook(conn, session_id="s1", hook_event="Stop", limit=10)
    assert first
    conn.execute(
        "UPDATE session_message_recipients "
        "SET injection_lease_expires_at='2000-01-01T00:00:00Z'"
    )
    conn.commit()

    second = lease_for_hook(conn, session_id="s1", hook_event="Stop", limit=10)
    assert second and second["lease_id"] != first["lease_id"]
    old = conn.execute(
        "SELECT completed_at,result_code FROM session_message_attempts "
        "WHERE lease_id=?",
        (first["lease_id"],),
    ).fetchone()
    assert old["completed_at"]
    assert old["result_code"] == "hook_lease_expired"


def test_central_expiry_closes_active_lease_and_prevents_completion() -> None:
    conn = message_connection()
    _send(conn)
    lease = lease_for_hook(conn, session_id="s1", hook_event="Stop", limit=10)
    assert lease

    assert expire_due_recipients(conn, now=NOW + timedelta(hours=25)) == 1
    assert (
        complete_hook_lease(
            conn, lease_id=lease["lease_id"], injected=True, result="injected"
        )
        == 0
    )
    receipt = conn.execute(
        "SELECT state,expired_at,injection_lease_id FROM session_message_recipients"
    ).fetchone()
    assert receipt["state"] == "expired"
    assert receipt["expired_at"]
    assert receipt["injection_lease_id"] is None
    attempt = conn.execute(
        "SELECT result_code FROM session_message_attempts"
    ).fetchone()
    assert attempt["result_code"] == "recipient_expired"


def test_wake_eligibility_keys_off_hook_activity_and_excludes_live_injected() -> None:
    conn = message_connection()
    message_id = _send(conn)
    pending = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11))
    assert [(row["message_id"], row["liveness"]) for row in pending] == [
        (message_id, "active")
    ]

    active_at = "2026-08-22T16:11:00Z"
    conn.execute(
        "UPDATE session_message_recipients SET state='injected',"
        "injection_count=1,last_injected_at=? WHERE message_id=?",
        (active_at, message_id),
    )
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=?,last_tool_call_at=? "
        "WHERE session_id='s1'",
        (active_at, active_at),
    )
    conn.commit()
    assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=20)) == []

    stale = wake_eligible_recipients(conn, now=NOW + timedelta(hours=3))
    assert [row["message_id"] for row in stale] == [message_id]


def test_waiting_pending_receipt_bypasses_idle_grace_without_an_injection_lease() -> (
    None
):
    conn = message_connection()
    stamp_turn_posture(
        conn,
        session_id="s1",
        posture="waiting",
        observed_at=NOW - timedelta(seconds=1),
    )
    conn.commit()
    message_id = _send(conn)

    rows = wake_eligible_recipients(conn, now=NOW + timedelta(seconds=1))

    assert [row["message_id"] for row in rows] == [message_id]


def test_running_unknown_and_injected_receipts_keep_existing_idle_grace() -> None:
    for posture in ("running", "unknown"):
        conn = message_connection()
        _send(conn)
        conn.execute(
            "UPDATE harness_sessions SET turn_posture=? WHERE session_id='s1'",
            (posture,),
        )
        conn.commit()
        assert wake_eligible_recipients(conn, now=NOW + timedelta(seconds=1)) == []

    conn = message_connection()
    _send(conn)
    conn.execute("UPDATE harness_sessions SET turn_posture='waiting'")
    conn.execute("UPDATE session_message_recipients SET state='injected'")
    conn.commit()
    assert wake_eligible_recipients(conn, now=NOW + timedelta(seconds=1)) == []


def test_waiting_receipt_with_injection_lease_does_not_wake_immediately() -> None:
    conn = message_connection()
    _send(conn)
    conn.execute("UPDATE harness_sessions SET turn_posture='waiting'")
    conn.execute(
        "UPDATE session_message_recipients SET injection_lease_id='hook-lease',"
        "injection_lease_expires_at='2026-08-22T16:01:00Z'"
    )
    conn.commit()

    assert wake_eligible_recipients(conn, now=NOW + timedelta(seconds=1)) == []
    conn.execute(
        "UPDATE session_message_recipients SET "
        "injection_lease_expires_at='2026-08-22T15:59:59Z'"
    )
    conn.commit()
    assert wake_eligible_recipients(conn, now=NOW + timedelta(seconds=1)) == []


def test_reinjection_policy_disables_both_repeat_hook_and_injected_wake() -> None:
    conn = message_connection()
    _send(conn)
    lease = lease_for_hook(conn, session_id="s1", hook_event="Stop", limit=10)
    assert lease
    complete_hook_lease(
        conn, lease_id=lease["lease_id"], injected=True, result="injected"
    )
    conn.execute(
        "UPDATE organizations SET settings=? WHERE id=1",
        (json.dumps({"fleet": {"reinject_until_acknowledged": False}}),),
    )
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat='2000-01-01T00:00:00Z',"
        "last_tool_call_at='2000-01-01T00:00:00Z' WHERE session_id='s1'"
    )
    conn.commit()
    assert lease_for_hook(conn, session_id="s1", hook_event="Stop", limit=10) is None
    assert wake_eligible_recipients(conn, now=NOW + timedelta(hours=1)) == []


def test_hook_completion_closes_bound_launch_in_the_same_mutation() -> None:
    conn = message_connection()
    message_id = _send(conn)
    conn.execute(
        "INSERT INTO session_launches "
        "(launch_id,requester_actor_id,project_id,requested_surface,selected_surface,message_id,"
        "state,registered_session_id,deadline_at,created_at) "
        "VALUES ('launch-1',10,1,'codex-desktop','codex-desktop',?,'awaiting_registration',"
        "'s1','2026-08-22T17:00:00Z',?)",
        (message_id, NOW_TEXT),
    )
    conn.commit()
    lease = lease_for_hook(conn, session_id="s1", hook_event="Stop", limit=10)
    assert lease
    complete_hook_lease(
        conn, lease_id=lease["lease_id"], injected=True, result="injected"
    )
    launch = conn.execute(
        "SELECT state,result_code FROM session_launches WHERE launch_id='launch-1'"
    ).fetchone()
    assert tuple(launch) == ("succeeded", "registered_and_injected")
