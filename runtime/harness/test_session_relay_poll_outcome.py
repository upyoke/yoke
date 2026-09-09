"""Daemon poll bursts persist a local outcome that status can read."""

from __future__ import annotations

import logging

from yoke_contracts.session_control.relay_health import (
    RELAY_NEWER_THAN_SERVER,
    sanitize_relay_health,
)
from yoke_harness.session_relay import ServeOnceOutcome
from yoke_harness.session_relay_daemon import serve_forever
from yoke_harness.session_relay_health import observe_relay_health
from yoke_harness.session_relay_poll_health import (
    diagnosed_poll_code,
    record_poll_success,
    reset_poll_outcome,
)


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


def test_poll_exception_does_not_persist_raw_exception_text(tmp_path) -> None:
    secret = "https://control.example/callback?token=super-secret"

    def cycle(**_kwargs) -> ServeOnceOutcome:
        raise ValueError(secret)

    serve_forever(
        state_dir=tmp_path,
        cycle=cycle,
        stop_after_cycles=1,
        idle_tick_seconds=0,
        install_signals=False,
    )

    poll = observe_relay_health(tmp_path)["poll_outcome"]
    assert poll["status"] == "failed"
    assert poll["error_code"] == "ValueError"
    assert secret not in str(poll)
    assert "https://" not in str(poll)


def test_error_detail_is_not_stored_when_a_diagnosed_code_exists(tmp_path) -> None:
    serve_forever(
        state_dir=tmp_path,
        cycle=lambda **_kwargs: ServeOnceOutcome(
            "claim_failed",
            error_code="machine_credential_required",
            error_detail="https://example.test/token=leak",
        ),
        stop_after_cycles=1,
        idle_tick_seconds=0,
        install_signals=False,
    )

    poll = observe_relay_health(tmp_path)["poll_outcome"]
    assert poll["error_code"] == "machine_credential_required"
    assert "https://" not in str(poll)


def test_build_refusal_logs_revisions_without_storing_them(tmp_path, caplog) -> None:
    caplog.set_level(logging.ERROR, logger="yoke_harness.session_relay_failure_log")
    serve_forever(
        state_dir=tmp_path,
        cycle=lambda **_kwargs: ServeOnceOutcome(
            RELAY_NEWER_THAN_SERVER,
            error_code=RELAY_NEWER_THAN_SERVER,
            error_detail=(
                f"{RELAY_NEWER_THAN_SERVER}: relay revision aaaaaaaaaaaa is 30 "
                "commit(s) ahead of server revision v0.1.1+launch.365; "
                "recovery: deploy"
            ),
        ),
        stop_after_cycles=1,
        idle_tick_seconds=0,
        install_signals=False,
    )

    assert "aaaaaaaaaaaa" in caplog.text
    poll = observe_relay_health(tmp_path)["poll_outcome"]
    assert poll["error_code"] == RELAY_NEWER_THAN_SERVER
    assert "aaaaaaaaaaaa" not in str(poll)


def test_unscoped_daemon_records_default_directory_startup_failure_and_recovery(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "yoke_harness.session_relay_daemon.relay_state_dir",
        lambda: tmp_path,
    )
    outcomes = iter(
        (
            ServeOnceOutcome("claim_failed", error_code="machine_credential_required"),
            ServeOnceOutcome("active", 1),
        )
    )

    serve_forever(
        cycle=lambda **_kwargs: next(outcomes),
        stop_after_cycles=2,
        idle_tick_seconds=0,
        install_signals=False,
    )

    poll = observe_relay_health(tmp_path)["poll_outcome"]
    assert poll["status"] == "ok"
    assert poll["last_failed_at"]
    assert poll["last_succeeded_at"]
    assert "error_code" not in poll


def test_diagnosed_poll_code_drops_urls_and_keeps_named_codes() -> None:
    assert diagnosed_poll_code("machine_credential_required") == (
        "machine_credential_required"
    )
    assert diagnosed_poll_code(ValueError("https://x.test/?token=1")) == "ValueError"
    assert diagnosed_poll_code("https://x.test/?token=1") == "poll_failed"


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
