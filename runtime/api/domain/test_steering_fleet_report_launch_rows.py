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
    line = unregistered_launch_lines(
        (_unregistered(state="outcome_unknown", observed_session_id="session-1"),)
    )[0]

    assert "registered session session-1 exists" in line
    assert "native is live — bind it" in line
    assert "launch reconcile launch-1 --observed-native-id session-1" in line
    assert "native is dead" not in line


def test_an_awaiting_registration_launch_offers_no_reconcile() -> None:
    line = unregistered_launch_lines((_unregistered(native_session_id="native-1"),))[0]

    assert "native session native-1 started; no session registered" in line
    assert "registered session" not in line
    assert "reconcile" not in line
    assert (
        "no command binds it in this state; relaunch once the native exits "
        "and the cause is fixed"
    ) in line


def test_a_dead_native_is_told_to_reconcile_then_retry_and_quotes_it() -> None:
    line = unregistered_launch_lines(
        (
            _unregistered(
                state="failed",
                observed_session_id="session-1",
                native_stderr_tail=REFUSAL,
                exit_code=1,
            ),
        )
    )[0]

    assert "native is dead — reconcile, then retry" in line
    assert "launch reconcile launch-1 --observed-native-id session-1" in line
    assert f"exit 1, last output: {REFUSAL}" in line


def test_a_correlation_failure_without_output_still_names_the_recovery() -> None:
    line = unregistered_launch_lines(
        (_unregistered(state="outcome_unknown", result_code="identity_listing_lagged"),)
    )[0]

    assert "identity listing lagged" in line
    assert "reconcile, then retry: find the native session ID" in line


def test_a_failed_launch_reconciled_as_never_created_only_relaunches() -> None:
    line = unregistered_launch_lines(
        (_unregistered(state="failed", result_code="reconciled_not_created"),)
    )[0]

    assert "reconciled as never created" in line
    assert "relaunch once the cause is fixed" in line
    assert "reconcile launch-1" not in line
    assert "--observed-native-id" not in line


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


def test_exited_unregistered_native_names_evidence_and_settlement():
    line = unregistered_launch_lines(
        (
            _unregistered(
                state="failed",
                result_code="native_exited_unregistered",
                exit_code=0,
                native_launch_pid=123,
                native_launch_phase="native_exited",
            ),
        )
    )[0]

    assert "native exited before any session registered" in line
    assert "native pid 123 native_exited" in line
    assert "exit 0" in line
    assert "worker never started" not in line
    assert "launch cancel launch-1" in line


def test_unregistered_excerpt_is_bounded_and_never_offers_a_session_read():
    line = unregistered_launch_lines((_unregistered(
        native_session_id="never-registered",
        evidence_id="nd-11111111-1111-4111-8111-111111111111",
        result_code="native_exited_unregistered",
        native_stderr_excerpt="old text\n" + "x" * 1000 + "\nfinal error",
        exit_code=1,
    ),))[0]

    assert "final error" in line
    assert "old text" not in line
    assert "…" in line
    assert "\n" not in line
    assert "evidence get" not in line
    assert len(line.split("last output: ")[1].split("; instruction")[0]) == 512
