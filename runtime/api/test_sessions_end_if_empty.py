"""Claim-aware session auto-end behavior."""

import json
from datetime import timedelta

from runtime.api.test_sessions import _insert_claimable_item, _register
from yoke_core.domain.session_control_schema import create_session_control_tables
from yoke_core.domain.session_launch_execution import claim_assigned_launch
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.session_launch_types import LaunchAuthorization, LaunchRequest
from yoke_core.domain.session_message_types import timestamp, utc_now
from yoke_core.domain.session_relay_launch_progress import report_launch_progress
from yoke_core.domain.sessions import claim_work, end_session_if_empty

pytest_plugins = ("runtime.api.test_sessions",)


def test_ends_claimless_active_session(conn):
    _register(conn, session_id="empty-end")

    result = end_session_if_empty(conn, "empty-end")

    assert result["status"] == "ended"
    assert result["ended"] is True
    row = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id='empty-end'"
    ).fetchone()
    assert row["ended_at"] is not None


def test_skips_session_with_active_claims(conn):
    _register(conn, session_id="claimed-end")
    _insert_claimable_item(conn, 9999)
    claim_work(conn, session_id="claimed-end", item_id=9999)

    result = end_session_if_empty(conn, "claimed-end")

    assert result["status"] == "has_claims"
    assert result["ended"] is False
    assert result["active_claim_count"] == 1
    row = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id='claimed-end'"
    ).fetchone()
    assert row["ended_at"] is None


def test_idempotent_when_already_ended(conn):
    _register(conn, session_id="already-ended")
    end_session_if_empty(conn, "already-ended")

    result = end_session_if_empty(conn, "already-ended")

    assert result["status"] == "already_ended"
    assert result["ended"] is False


def _woken_recipient(conn, session_id: str, *, wake_age_s: int, state="pending"):
    """Seed one message this session was woken for, waked ``wake_age_s`` ago.

    This fixture carries no organization policy, so the window under test is
    the registry's declared ``fleet.wake_ack_grace_seconds`` default - which
    is also the path a universe takes when its policy cannot be resolved.
    """
    from datetime import timedelta

    from yoke_core.domain.session_control_schema import create_session_control_tables
    from yoke_core.domain.session_message_types import timestamp, utc_now

    create_session_control_tables(conn)
    now = utc_now()
    message_id = f"message-for-{session_id}"
    row = conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO actors (kind, created_at) VALUES ('human', %s)",
            (timestamp(now),),
        )
        row = conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()
    actor_id = row["id"]
    conn.execute(
        "INSERT INTO session_messages (message_id,sender_actor_id,body,body_sha256,"
        "selector_snapshot,created_at,expires_at) VALUES (%s,%s,'wake','sha','{}',%s,%s)",
        (message_id, actor_id, timestamp(now), timestamp(now + timedelta(hours=1))),
    )
    conn.execute(
        "INSERT INTO session_message_recipients (message_id,session_id,project_id,"
        "resolution_evidence,routing_snapshot,state,created_at,wake_after,"
        "wake_attempt_count,last_wake_at) "
        "VALUES (%s,%s,1,'{}','{}',%s,%s,%s,1,%s)",
        (
            message_id,
            session_id,
            state,
            timestamp(now),
            timestamp(now),
            timestamp(now - timedelta(seconds=wake_age_s)),
        ),
    )
    conn.commit()


def test_skips_session_inside_its_wake_delivery_window(conn):
    """A wake starts a turn so a hook inside it can inject; between the two
    the session holds nothing, and ending it there reaps the turn the wake
    paid for. Every later wake then finds an ended session and repeats."""
    _register(conn, session_id="woken-end")
    _woken_recipient(conn, "woken-end", wake_age_s=5)

    result = end_session_if_empty(conn, "woken-end")

    assert result["status"] == "wake_delivery_in_flight"
    assert result["ended"] is False
    assert result["message_id"] == "message-for-woken-end"
    assert result["recipient_state"] == "pending"
    row = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id='woken-end'"
    ).fetchone()
    assert row["ended_at"] is None


def test_ends_session_once_the_wake_delivery_window_closes(conn):
    """The window is the acknowledgement grace, not an open-ended hold: a
    wake that never landed must not keep an idle session alive forever."""
    _register(conn, session_id="stale-wake-end")
    _woken_recipient(conn, "stale-wake-end", wake_age_s=301)

    result = end_session_if_empty(conn, "stale-wake-end")

    assert result["status"] == "ended"
    assert result["ended"] is True


def test_ends_session_when_the_woken_message_was_acknowledged(conn):
    """Delivery is done, so the turn the wake paid for is done too."""
    _register(conn, session_id="acked-wake-end")
    _woken_recipient(conn, "acked-wake-end", wake_age_s=5, state="acknowledged")

    result = end_session_if_empty(conn, "acked-wake-end")

    assert result["status"] == "ended"
    assert result["ended"] is True


def test_skips_registered_session_while_its_launch_is_pending_binding(conn):
    create_session_control_tables(conn)
    now = utc_now()
    started_at = timestamp(now)
    machine_id = "33333333-3333-4333-8333-333333333333"
    session_id = "87654321-4321-4321-8321-cba987654321"
    actor_id = int(
        conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    )
    conn.execute(
        "INSERT INTO session_relays ("
        "relay_id,actor_id,machine_id,hostname,surface_versions,project_checkouts,"
        "first_seen_at,last_seen_at,connected_until,state) "
        "VALUES ('relay-registration-hold',%s,%s,'relay-host',%s,%s,%s,%s,%s,'active')",
        (
            actor_id,
            machine_id,
            json.dumps({"claude-cli": "2.1.238"}),
            json.dumps([1]),
            started_at,
            started_at,
            timestamp(now + timedelta(minutes=10)),
        ),
    )
    conn.commit()
    launch = create_launch(
        conn,
        auth=LaunchAuthorization(
            actor_id=actor_id,
            session_id=None,
            can_operate_project=True,
        ),
        request=LaunchRequest(
            project_id=1,
            executor_surface="claude-cli",
            instructions="Wait for the automatic launch instruction.",
            idempotency_key="pending-registration-end-hold",
            machine_id=machine_id,
            presentation="local",
        ),
        now=started_at,
    ).launch
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-registration-hold",
        machine_id=machine_id,
        now=started_at,
    )
    report_launch_progress(
        conn,
        relay_id="relay-registration-hold",
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        adapter_revision="claude-native-v7",
        evidence={
            "result_code": "native_spawn_pending",
            "native_launch_phase": "spawn_started",
            "native_launch_pid": 4242,
            "native_launch_workspace": "/tmp/work",
            "native_launch_bound_seconds": 180,
        },
        now=started_at,
    )
    _register(
        conn,
        session_id=session_id,
        executor="claude-code",
        entrypoint="cli",
        executor_version="2.1.238",
        machine_id=machine_id,
    )

    result = end_session_if_empty(conn, session_id)

    assert result["status"] == "launch_delivery_pending"
    assert result["ended"] is False
    assert result["launch_id"] == launch.launch_id
    assert result["launch_count"] == 1
    assert result["recovery"] == (
        f"yoke session-control launch get {launch.launch_id} --json"
    )
    row = conn.execute(
        "SELECT ended_at FROM harness_sessions WHERE session_id=%s", (session_id,)
    ).fetchone()
    assert row["ended_at"] is None
