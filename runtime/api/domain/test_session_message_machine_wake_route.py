"""An IDE session is woken by a qualified CLI on its own machine.

A desktop session is not, at any version: its capability declares the
operator as the waker, so the peer route the IDE surfaces depend on is
never composed for one, and the refusal is recorded where an operator
reads it.
"""

from __future__ import annotations

from runtime.api.domain.session_message_machine_wake_route_test_support import (
    MACHINE_ID as MACHINE_ID,
    RELAY_ID as RELAY_ID,
    STALE_ACTIVITY as STALE_ACTIVITY,
    WAKE_TIME as WAKE_TIME,
    _heartbeat as _heartbeat,
    _register_relay as _register_relay,
    _send as _send,
    _snapshot_route as _snapshot_route,
    _surface_connection as _surface_connection,
)


import json
from datetime import timedelta

import pytest


from yoke_core.domain.session_message_store import message_details
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_control_roster import session_control_roster_result
from yoke_core.domain.session_relay import claim_relay_job
from runtime.api.domain.session_message_support_test_support import (
    NOW,
)


IDE_VERSION = "2.1.238"
DESKTOP_VERSION = "1.32885.1"
QUALIFIED_CLI = "2.1.241"
BELOW_FLOOR_CLI = "2.1.200"
CURSOR_DESKTOP_VERSION = "3.17.8"
CURSOR_CLI_VERSION = "2026.08.11-e8db854"


def _stopped_ide_connection():
    return _surface_connection(
        executor="claude-code",
        surface="claude-vscode",
        version=IDE_VERSION,
        ended=True,
    )


def test_send_snapshot_routes_a_stopped_ide_session_through_the_machine_cli():
    conn = _stopped_ide_connection()
    _register_relay(conn, {"claude-cli": QUALIFIED_CLI})

    routing = _snapshot_route(conn, _send(conn))

    assert routing["wake_operation"] == "message_stopped"
    assert routing["wake_interface"] == "supported"


def test_send_snapshot_reports_no_route_without_a_qualified_machine_cli():
    bare = _stopped_ide_connection()
    assert _snapshot_route(bare, _send(bare))["wake_interface"] == "none"

    stale = _stopped_ide_connection()
    _register_relay(stale, {"claude-cli": BELOW_FLOOR_CLI})
    assert _snapshot_route(stale, _send(stale))["wake_interface"] == "none"


def test_machine_cli_makes_a_stopped_ide_recipient_wake_eligible_after_backoff():
    conn = _stopped_ide_connection()
    _send(conn)
    assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11)) == []

    _register_relay(conn, {"claude-cli": QUALIFIED_CLI})
    eligible = wake_eligible_recipients(conn, now=NOW + timedelta(minutes=12))

    assert [row["session_id"] for row in eligible] == ["s2"]
    assert eligible[0]["executor_surface"] == "claude-vscode"


def test_wake_job_carries_the_executing_cli_rather_than_the_registered_surface():
    conn = _stopped_ide_connection()
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
    # The relay dispatches by job surface, and claude-vscode has no resume
    # adapter, so the job must name the binary that performs the resume.
    assert job.surface == "claude-cli"
    assert job.surface_version == QUALIFIED_CLI


@pytest.mark.parametrize(
    ("executor", "surface", "version", "cli_surface", "cli_version"),
    (
        ("claude-code", "claude-desktop", DESKTOP_VERSION, "claude-cli", QUALIFIED_CLI),
        (
            "cursor",
            "cursor-desktop",
            CURSOR_DESKTOP_VERSION,
            "cursor-cli",
            CURSOR_CLI_VERSION,
        ),
    ),
)
@pytest.mark.parametrize("ended", (False, True))
def test_an_installed_cli_never_wakes_a_desktop_session(
    executor: str,
    surface: str,
    version: str,
    cli_surface: str,
    cli_version: str,
    ended: bool,
) -> None:
    """The qualified peer binary is present and still names no route.

    Idle or stopped, the binary that could perform the resume is exactly
    the thing that would fork the operator's transcript, so no snapshot
    route, no roster route, and no relay job is minted for it.
    """
    conn = _surface_connection(
        executor=executor, surface=surface, version=version, ended=ended
    )
    versions = {cli_surface: cli_version}
    _register_relay(conn, versions)
    message_id = _send(conn)

    routing = _snapshot_route(conn, message_id)
    assert routing["wake_interface"] == "none"
    assert routing["wake_authority"] == "operator"
    # Delivery is untouched: the hook still carries the envelope.
    assert routing["hook_injection"] is True
    roster = session_control_roster_result(
        [{"session_id": "s2", "liveness": "ended" if ended else "stale"}],
        conn=conn,
        now=NOW,
    )["rows"][0]["messageability"]
    assert roster["wake_available"] is False
    outcome = claim_relay_job(
        conn,
        _heartbeat(versions),
        wait_seconds=0,
        now_provider=lambda: WAKE_TIME,
    )

    assert outcome.jobs == ()


@pytest.mark.parametrize(
    (
        "executor",
        "surface",
        "version",
        "relay_versions",
        "ended",
        "result_code",
        "reason",
    ),
    (
        (
            "claude-code",
            "claude-vscode",
            IDE_VERSION,
            {},
            True,
            "skipped_surface",
            "peer_driver_not_installed",
        ),
        (
            "claude-code",
            "claude-vscode",
            IDE_VERSION,
            {"claude-cli": BELOW_FLOOR_CLI},
            True,
            "skipped_version",
            "peer_driver_version_below_floor",
        ),
        # The one refusal no upgrade and no installed peer can lift.
        (
            "claude-code",
            "claude-desktop",
            DESKTOP_VERSION,
            {"claude-cli": QUALIFIED_CLI},
            False,
            "skipped_operation",
            "operator",
        ),
    ),
)
def test_capability_refusal_records_one_observable_wake_skip(
    executor: str,
    surface: str,
    version: str,
    relay_versions: dict[str, str],
    ended: bool,
    result_code: str,
    reason: str,
) -> None:
    conn = _surface_connection(
        executor=executor,
        surface=surface,
        version=version,
        ended=ended,
    )
    if relay_versions:
        _register_relay(conn, relay_versions)
    message_id = _send(conn)

    for _ in range(2):
        assert wake_eligible_recipients(conn, now=NOW + timedelta(minutes=11)) == []

    details = message_details(conn, message_id)
    assert details["attempt_count"] == 1
    assert details["attempts"][0]["result_code"] == result_code
    # The bare code cannot separate "no route exists" from "the peer binary
    # is missing"; the recorded rule is what an operator reads instead.
    evidence = details["attempts"][0]["evidence"]
    evidence = json.loads(evidence) if isinstance(evidence, str) else evidence
    assert evidence["skip_reason"] == reason
    assert evidence["turn_posture"] == ("waiting" if ended else "running")
    assert evidence["liveness"] == ("ended" if ended else "stale")
    assert details["attempts"][0]["completed_at"] is not None
    assert details["recipients"][0]["wake_attempt_count"] == (
        0 if reason == "operator" else 1
    )


def test_no_wake_job_is_minted_when_the_machine_cli_is_below_its_floor():
    conn = _stopped_ide_connection()
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
        == 1
    )
