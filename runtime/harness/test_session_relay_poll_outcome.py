"""Daemon poll bursts persist a local outcome that status can read."""

from __future__ import annotations

from yoke_contracts.session_control.relay_health import sanitize_relay_health
from yoke_harness.session_relay import ServeOnceOutcome
from yoke_harness.session_relay_daemon import serve_forever
from yoke_harness.session_relay_health import observe_relay_health
from yoke_harness.session_relay_poll_health import record_poll_success, reset_poll_outcome


def test_repeated_claim_failure_keeps_the_current_burst_count(tmp_path) -> None:
    outcomes = iter(
        (
            ServeOnceOutcome("claim_failed", error_code="machine_credential_required"),
            ServeOnceOutcome("claim_failed", error_code="machine_credential_required"),
        )
    )

    serve_forever(
        state_dir=tmp_path,
        cycle=lambda **_kwargs: next(outcomes),
        stop_after_cycles=2,
        idle_tick_seconds=0,
        install_signals=False,
    )

    poll = observe_relay_health(tmp_path)["poll_outcome"]
    assert poll["status"] == "failed"
    assert poll["error_code"] == "machine_credential_required"
    assert poll["consecutive_failures"] == 2


def test_repeated_claim_failure_counts_then_success_clears_current_failure(tmp_path) -> None:
    outcomes = iter(
        (
            ServeOnceOutcome("claim_failed", error_code="machine_credential_required"),
            ServeOnceOutcome("claim_failed", error_code="machine_credential_required"),
            ServeOnceOutcome("active", 1),
        )
    )

    serve_forever(
        state_dir=tmp_path,
        cycle=lambda **_kwargs: next(outcomes),
        stop_after_cycles=3,
        idle_tick_seconds=0,
        install_signals=False,
    )

    health = observe_relay_health(tmp_path)
    poll = health["poll_outcome"]
    assert health["state"] == "healthy"
    assert poll["status"] == "ok"
    assert "error_code" not in poll
    assert poll["last_failed_at"]
    assert poll["last_succeeded_at"]
    assert sanitize_relay_health(health).get("poll_outcome") is None


def test_poll_exception_records_the_safe_reason(tmp_path) -> None:
    calls: list[int] = []

    def cycle(**_kwargs) -> ServeOnceOutcome:
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("server rejected relay payload")
        return ServeOnceOutcome("active", 1)

    serve_forever(
        state_dir=tmp_path,
        cycle=cycle,
        stop_after_cycles=2,
        idle_tick_seconds=0,
        install_signals=False,
    )

    poll = observe_relay_health(tmp_path)["poll_outcome"]
    assert poll["status"] == "ok"
    assert poll["last_failed_at"]


def test_startup_clears_inherited_success_before_the_first_poll(tmp_path) -> None:
    record_poll_success(tmp_path)
    reset_poll_outcome(tmp_path)
    started = observe_relay_health(tmp_path)["poll_outcome"]
    assert started["status"] == "pending"
    assert started["last_succeeded_at"]

    serve_forever(
        state_dir=tmp_path,
        cycle=lambda **_kwargs: ServeOnceOutcome("active", 1),
        stop_after_cycles=1,
        idle_tick_seconds=0,
        install_signals=False,
    )

    poll = observe_relay_health(tmp_path)["poll_outcome"]
    assert poll["status"] == "ok"
