"""Launch rows carry the native's own reason and the hand each one needs."""

from __future__ import annotations

from yoke_core.domain.steering_fleet_report_abandoned import AbandonedLaunch
from yoke_core.domain.steering_fleet_report_detectors import UnregisteredLaunch
from yoke_core.domain.steering_fleet_report_render_launches import (
    abandoned_launch_lines,
    unregistered_launch_lines,
)


REFUSAL = "credit balance is too low"


def _unregistered(**overrides) -> UnregisteredLaunch:
    fields = {
        "launch_id": "launch-1",
        "surface": "claude-cli",
        "machine_id": "machine-1",
        "state": "awaiting_registration",
        "overdue_seconds": 120,
    }
    fields.update(overrides)
    return UnregisteredLaunch(**fields)


def test_a_live_unbound_native_is_told_to_be_bound() -> None:
    line = unregistered_launch_lines((_unregistered(observed_session_id="session-1"),))[
        0
    ]

    assert "native is live — bind it" in line
    assert "launch reconcile launch-1 --observed-native-id session-1" in line
    assert "native is dead" not in line


def test_a_dead_native_is_told_to_reconcile_then_retry_and_quotes_it() -> None:
    line = unregistered_launch_lines(
        (
            _unregistered(
                observed_session_id="session-1",
                native_stderr_tail=REFUSAL,
                exit_code=1,
            ),
        )
    )[0]

    assert "native is dead — reconcile, then retry" in line
    assert f"exit 1, last output: {REFUSAL}" in line


def test_a_correlation_failure_without_output_still_names_the_recovery() -> None:
    line = unregistered_launch_lines(
        (_unregistered(result_code="identity_listing_lagged"),)
    )[0]

    assert "identity listing lagged" in line
    assert "reconcile, then retry" in line


def test_an_abandoned_launch_names_the_session_the_reason_and_the_action() -> None:
    line = abandoned_launch_lines(
        (
            AbandonedLaunch(
                launch_id="launch-1",
                surface="claude-cli",
                machine_id="machine-1",
                session_id="session-1",
                closed_seconds=3600,
                closure_reason="native_process_gone",
                native_stderr_tail=REFUSAL,
                exit_code=1,
            ),
        )
    )[0]

    assert "session session-1 read its mandate and never started" in line
    assert "closed 1h00m ago" in line
    assert f"exit 1, last output: {REFUSAL}" in line
    assert "its work is unstarted — restaff it" in line


def test_an_abandoned_launch_that_said_nothing_says_so() -> None:
    line = abandoned_launch_lines(
        (
            AbandonedLaunch(
                launch_id="launch-1",
                surface="codex-cli",
                machine_id="machine-1",
                session_id="session-1",
                closed_seconds=45,
                exit_code=0,
            ),
        )
    )[0]

    assert "exit 0, no output" in line
