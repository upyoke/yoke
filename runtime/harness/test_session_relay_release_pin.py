"""Background relay release installs: interruptible children and visible state."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time

import pytest

from yoke_cli.commands.adapters.session_control_relay_output import (
    relay_status_fields,
)
from yoke_cli.transport import control_plane_payload
from yoke_harness.session_relay import ServeOnceOutcome
from yoke_harness.session_relay_daemon import serve_forever
from yoke_harness.session_relay_health import observe_relay_health
from yoke_harness.session_relay_release_pin import (
    InterruptibleRunner,
    ReleasePinCancelled,
    record_release_pin_failed,
    record_release_pin_started,
)

_SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]


def test_runner_returns_what_subprocess_run_returns() -> None:
    result = InterruptibleRunner()(
        [sys.executable, "-c", "import sys; print('out'); sys.exit(3)"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 3
    assert result.stdout.strip() == "out"
    with pytest.raises(subprocess.TimeoutExpired):
        InterruptibleRunner()(_SLEEP, capture_output=True, timeout=0.2)


def test_cancel_kills_the_running_child_and_names_the_cancellation() -> None:
    runner = InterruptibleRunner()
    raised: list[BaseException] = []

    def install() -> None:
        try:
            runner(_SLEEP, capture_output=True, text=True)
        except BaseException as exc:  # noqa: BLE001 — recorded for the assertion
            raised.append(exc)

    thread = threading.Thread(target=install)
    thread.start()
    time.sleep(0.3)
    started = time.monotonic()
    runner.cancel()
    thread.join(10)

    assert not thread.is_alive()
    assert time.monotonic() - started < 10
    assert isinstance(raised[0], ReleasePinCancelled)
    assert raised[0].code == "relay_release_install_cancelled"
    with pytest.raises(ReleasePinCancelled):
        runner(_SLEEP)


def test_stopping_the_daemon_kills_the_install_instead_of_waiting(tmp_path) -> None:
    outcomes: list[object] = []

    def pin(build: str, *, runner):
        try:
            runner(_SLEEP, capture_output=True, text=True)
        except BaseException as exc:
            outcomes.append(exc)
            raise
        outcomes.append("finished")

    def cycle(**_kwargs) -> ServeOnceOutcome:
        control_plane_payload.observe_server_build("0.2.0.202611180002")
        time.sleep(0.1)
        return ServeOnceOutcome("active", 1)

    started = time.monotonic()
    outcome = serve_forever(
        state_dir=tmp_path,
        cycle=cycle,
        stop_after_cycles=3,
        idle_tick_seconds=0.01,
        install_signals=False,
        pinned_release="0.2.0.202611180001",
        pin_served_release=pin,
    )

    assert outcome.reason == "cycle_cap"
    assert time.monotonic() - started < 15
    assert len(outcomes) == 1 and isinstance(outcomes[0], ReleasePinCancelled)


def test_relay_status_shows_the_install_in_flight_and_the_last_failure(
    tmp_path,
) -> None:
    record_release_pin_failed(tmp_path, "0.2.0.202611180002", "relay_release_fetch_failed")
    record_release_pin_started(tmp_path, "0.2.0.202611180003")

    health = observe_relay_health(tmp_path)
    fields = dict(relay_status_fields({"relay_health": health}))

    in_flight = health["release_pin"]["in_flight"]
    assert in_flight["served_build"] == "0.2.0.202611180003"
    assert in_flight["elapsed_seconds"] >= 0
    assert fields["Release install in flight"].startswith(
        f"0.2.0.202611180003 since {in_flight['started_at']} ("
    )
    assert fields["Last release install failure"].startswith(
        "0.2.0.202611180002: relay_release_fetch_failed at "
    )


def test_install_log_counts_polls_completed_while_it_ran(tmp_path, caplog) -> None:
    finish = threading.Event()
    cycles: list[int] = []
    replacement = tmp_path / "venv" / "bin" / "yoke"

    def pin(build: str, **_kwargs):
        assert finish.wait(10)
        return replacement

    def cycle(**_kwargs) -> ServeOnceOutcome:
        cycles.append(1)
        if len(cycles) == 4:
            finish.set()
            time.sleep(0.1)
        control_plane_payload.observe_server_build("0.2.0.202611180002")
        return ServeOnceOutcome("active", 1)

    caplog.set_level(logging.WARNING, logger="yoke_harness.session_relay_release_pin")
    outcome = serve_forever(
        state_dir=tmp_path,
        cycle=cycle,
        idle_tick_seconds=0.01,
        install_signals=False,
        pinned_release="0.2.0.202611180001",
        pin_served_release=pin,
        reload_exec=lambda argv=None, **_kw: None,
    )

    messages = [record.getMessage() for record in caplog.records]
    assert outcome.reason == "served_build_changed"
    assert any("install started for 0.2.0.202611180002" in line for line in messages)
    verified = [line for line in messages if "install verified" in line]
    assert len(verified) == 1 and "outcome=switching" in verified[0]
    polls = int(verified[0].split("polls_during_install=")[1].split()[0])
    assert polls >= 2
    assert "release_pin" not in observe_relay_health(tmp_path)
