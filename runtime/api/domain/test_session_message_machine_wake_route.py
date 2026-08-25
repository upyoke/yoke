"""Desktop sessions are woken by a qualified CLI on their own machine."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_store import message_details, public_recipients
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_control_roster import session_control_roster_result
from yoke_core.domain.session_relay import claim_relay_job
from yoke_core.domain.session_relay_types import RelayHeartbeat
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
    selector,
)


MACHINE_ID = "22222222-2222-4222-8222-222222222222"
RELAY_ID = f"machine:{MACHINE_ID}"
DESKTOP_VERSION = "1.32885.1"
QUALIFIED_CLI = "2.1.241"
BELOW_FLOOR_CLI = "2.1.200"
CURSOR_DESKTOP_VERSION = "3.17.8"
CURSOR_CLI_VERSION = "2026.08.11-e8db854"
WAKE_TIME = "2026-08-22T16:11:00Z"
STALE_ACTIVITY = (NOW - timedelta(minutes=120)).isoformat().replace("+00:00", "Z")


def _surface_connection(*, executor: str, surface: str, version: str, ended: bool):
    conn = message_connection()
    conn.execute(
        "UPDATE harness_sessions SET executor=?,executor_surface=?,"
        "executor_version=?,machine_id=?,last_heartbeat=?,last_tool_call_at=?,"
        "turn_posture='running',ended_at=? WHERE session_id='s2'",
        (
            executor,
            surface,
            version,
            MACHINE_ID,
            NOW_TEXT if ended else STALE_ACTIVITY,
            NOW_TEXT if ended else STALE_ACTIVITY,
            NOW_TEXT if ended else None,
        ),
    )
    conn.commit()
    return conn


def _stopped_desktop_connection():
    return _surface_connection(
        executor="claude-code",
        surface="claude-desktop",
        version=DESKTOP_VERSION,
        ended=True,
    )


def _register_relay(conn, surface_versions: dict[str, str]) -> None:
    conn.execute(
        "INSERT INTO session_relays (relay_id,actor_id,machine_id,hostname,"
        "relay_version,surface_versions,project_checkouts,first_seen_at,"
        "last_seen_at,connected_until,state) VALUES (?,?,?,?,?,?,?,?,?,?,'active')",
        (
            RELAY_ID,
            10,
            MACHINE_ID,
            "dev-relay",
            "0.1.1",
            json.dumps(surface_versions),
            json.dumps([1]),
            NOW_TEXT,
            NOW_TEXT,
            "2026-08-23T00:00:00Z",
        ),
    )
    conn.commit()


def _heartbeat(surface_versions: dict[str, str]) -> RelayHeartbeat:
    return RelayHeartbeat(
        relay_id=RELAY_ID,
        actor_id=10,
        machine_id=MACHINE_ID,
        hostname="dev-relay",
        relay_version="0.1.1",
        surface_versions=dict(surface_versions),
        project_ids=(1,),
    )


def _send(conn) -> str:
    return str(
        send_message(
            conn,
            actor_id=10,
            sender_session_id="s1",
            selector=selector(session_ids=["s2"]),
            body="Body stays server-side through every wake route.",
            now=NOW,
        )["message_id"]
    )


def _snapshot_route(conn, message_id: str) -> dict:
    recipient = public_recipients(message_details(conn, message_id))[0]
    return dict(recipient["messageability"])


def test_send_snapshot_routes_a_stopped_desktop_session_through_the_machine_cli():
    conn = _stopped_desktop_connection()
    _register_relay(conn, {"claude-cli": QUALIFIED_CLI})

    routing = _snapshot_route(conn, _send(conn))

    assert routing["wake_operation"] == "message_stopped"
    assert routing["wake_interface"] == "supported"


def test_send_snapshot_reports_no_route_without_a_qualified_machine_cli():
    bare = _stopped_desktop_connection()
    assert _snapshot_route(bare, _send(bare))["wake_interface"] == "none"

    stale = _stopped_desktop_connection()
    _register_relay(stale, {"claude-cli": BELOW_FLOOR_CLI})
    assert _snapshot_route(stale, _send(stale))["wake_interface"] == "none"


def test_machine_cli_makes_a_stopped_desktop_recipient_wake_eligible():
    conn = _stopped_desktop_connection()
    _send(conn)
    assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11)) == []

    _register_relay(conn, {"claude-cli": QUALIFIED_CLI})
    eligible = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11))

    assert [row["session_id"] for row in eligible] == ["s2"]
    assert eligible[0]["executor_surface"] == "claude-desktop"


def test_wake_job_carries_the_executing_cli_rather_than_the_registered_surface():
    conn = _stopped_desktop_connection()
    _register_relay(conn, {"claude-cli": QUALIFIED_CLI})
    message_id = _send(conn)

    outcome = claim_relay_job(
        conn,
        _heartbeat({"claude-cli": QUALIFIED_CLI}),
        wait_seconds=0,
        now_provider=lambda: WAKE_TIME,
    )

    # Wakes stay serial, so one poll leases exactly one of them.
    assert len(outcome.jobs) == 1
    job = outcome.jobs[0]
    assert job.message_id == message_id
    assert job.target_session_id == "s2"
    assert job.wake_route == "direct"
    # The relay dispatches by job surface, and claude-desktop has no resume
    # adapter, so the job must name the binary that performs the resume.
    assert job.surface == "claude-cli"
    assert job.surface_version == QUALIFIED_CLI


@pytest.mark.parametrize(
    ("ended", "operation"),
    ((False, "message_idle"), (True, "message_stopped")),
)
def test_cursor_desktop_wakes_through_the_installed_cursor_cli(
    ended: bool, operation: str
) -> None:
    conn = _surface_connection(
        executor="cursor",
        surface="cursor-desktop",
        version=CURSOR_DESKTOP_VERSION,
        ended=ended,
    )
    versions = {"cursor-cli": CURSOR_CLI_VERSION}
    _register_relay(conn, versions)
    message_id = _send(conn)

    assert _snapshot_route(conn, message_id)["wake_operation"] == operation
    roster = session_control_roster_result(
        [{"session_id": "s2", "liveness": "ended" if ended else "stale"}],
        conn=conn,
        now=NOW,
    )["rows"][0]["messageability"]
    assert roster["wake_operation"] == operation
    assert roster["wake_available"] is True
    outcome = claim_relay_job(
        conn,
        _heartbeat(versions),
        wait_seconds=0,
        now_provider=lambda: WAKE_TIME,
    )

    assert len(outcome.jobs) == 1
    assert outcome.jobs[0].surface == "cursor-cli"
    assert outcome.jobs[0].surface_version == CURSOR_CLI_VERSION


@pytest.mark.parametrize(
    ("executor", "surface", "version", "relay_versions", "result_code"),
    (
        ("cursor", "cursor-desktop", CURSOR_DESKTOP_VERSION, {}, "skipped_surface"),
        (
            "cursor",
            "cursor-desktop",
            CURSOR_DESKTOP_VERSION,
            {"cursor-cli": "2026.08.10-deadbee"},
            "skipped_version",
        ),
        (
            "codex",
            "codex-cli",
            "0.148.0-alpha.15",
            {"codex-cli": "0.148.0-alpha.15"},
            "skipped_operation",
        ),
    ),
)
def test_capability_refusal_records_one_observable_wake_skip(
    executor: str,
    surface: str,
    version: str,
    relay_versions: dict[str, str],
    result_code: str,
) -> None:
    conn = _surface_connection(
        executor=executor,
        surface=surface,
        version=version,
        ended=False,
    )
    if relay_versions:
        _register_relay(conn, relay_versions)
    message_id = _send(conn)

    for _ in range(2):
        assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11)) == []

    details = message_details(conn, message_id)
    assert details["attempt_count"] == 1
    assert details["attempts"][0]["result_code"] == result_code
    assert details["attempts"][0]["completed_at"] is not None
    assert details["recipients"][0]["wake_attempt_count"] == 0


def test_no_wake_job_is_minted_when_the_machine_cli_is_below_its_floor():
    conn = _stopped_desktop_connection()
    _register_relay(conn, {"claude-cli": BELOW_FLOOR_CLI})
    _send(conn)

    outcome = claim_relay_job(
        conn,
        _heartbeat({"claude-cli": BELOW_FLOOR_CLI}),
        wait_seconds=0,
        now_provider=lambda: WAKE_TIME,
    )

    assert outcome.jobs == ()
    assert (
        conn.execute(
            "SELECT wake_attempt_count FROM session_message_recipients"
        ).fetchone()[0]
        == 0
    )
