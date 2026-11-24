"""The active relay polls through CLI follow and serializes release changes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from queue import Queue
from threading import Event, Thread, current_thread
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters.session_control_relay_release import serve_release_daemon
from yoke_cli.config import operator_cli_release_follow as follow
from yoke_cli.config import operator_cli_release_follow_worker
from yoke_contracts.machine_config import relay_instance
from yoke_core.tools import session_relay_release, session_relay_release_install
from yoke_harness import session_relay_daemon, session_relay_process_restart

RELEASE = "0.2.0.202611202031"
NEXT_RELEASE = "0.2.0.202611202101"
TIMEOUT = 5


@pytest.fixture
def active_relay(monkeypatch, tmp_path):
    instance = SimpleNamespace(
        environment="prod", state_dir=tmp_path, follows_served_release=True,
        machine_active=True,
    )
    monkeypatch.setattr(relay_instance, "resolve_relay_instance", lambda: instance)
    monkeypatch.setattr(
        session_relay_release, "relay_release_status",
        lambda **_kwargs: SimpleNamespace(
            current=True, pinned_release=RELEASE,
            runtime_python=Path(sys.prefix) / "bin" / "python",
        ),
    )
    return instance


def _join(thread):
    thread.join(timeout=TIMEOUT)
    assert not thread.is_alive()


@pytest.mark.parametrize("deferred_first", [False, True])
def test_relay_claims_during_initial_follow_and_during_retry(
    monkeypatch, active_relay, deferred_first,
):
    allow_finish = Event()
    attempts = []
    started = Queue()
    claims = []
    state_dir = active_relay.state_dir

    def follow_release(release, directory):
        assert directory == state_dir
        assert release == RELEASE
        attempts.append(release)
        started.put(current_thread())
        if deferred_first and len(attempts) == 1:
            return {"outcome": follow.DEFERRED_SETUP_ACTIVE}
        assert allow_finish.wait(timeout=TIMEOUT)
        return follow._finish({"release": release, "after": release}, directory, "updated")

    def cycle():
        claims.append(len(attempts))

    def serve_forever(*, cycle_maintenance, **_kwargs):
        assert attempts == []
        cycle_maintenance()
        worker = started.get(timeout=TIMEOUT)
        if deferred_first:
            _join(worker)
            assert attempts == [RELEASE]
            cycle_maintenance()
            worker = started.get(timeout=TIMEOUT)
        try:
            assert worker.is_alive()
            for _ in range(3):
                cycle_maintenance()
                cycle()
            assert worker.is_alive()
            assert claims == [1 + deferred_first] * 3
            assert attempts == [RELEASE] * (1 + deferred_first)
            assert not (state_dir / follow.FOLLOW_RECORD_NAME).exists()
        finally:
            allow_finish.set()
            _join(worker)
        cycle_maintenance()
        record = json.loads((state_dir / follow.FOLLOW_RECORD_NAME).read_text(encoding="utf-8"))
        assert record["outcome"] == "updated"
        assert record["after"] == RELEASE

    monkeypatch.setattr(follow, "follow_release", follow_release)
    monkeypatch.setattr(session_relay_daemon, "serve_forever", serve_forever)
    serve_release_daemon()


def test_locked_relay_does_not_start_a_follow(monkeypatch, active_relay):
    def unexpected_follow(*_args):
        pytest.fail("a relay without the run lock started an installer")

    monkeypatch.setattr(follow, "follow_release", unexpected_follow)
    monkeypatch.setattr(
        session_relay_daemon, "serve_forever",
        lambda **_kwargs: session_relay_daemon.DaemonOutcome("locked"),
    )
    assert serve_release_daemon().reason == "locked"


def test_served_build_change_waits_for_follow_before_pinning_and_restarting(
    monkeypatch, active_relay,
):
    release_follow = Event()
    waiting_to_pin = Event()
    started = Event()
    events = []
    replacement = active_relay.state_dir / "replacement"

    class FollowThread(Thread):
        def join(self, timeout=None):
            waiting_to_pin.set()
            super().join(timeout=timeout)

    def follow_release(_release, _directory):
        started.set()
        assert release_follow.wait(timeout=TIMEOUT)
        events.append("follow complete")
        # Even a follow that requests a retry must let the new pin proceed.
        return {"outcome": follow.DEFERRED_SETUP_ACTIVE}

    def pin(*, instance, served_build, runner):
        assert served_build == NEXT_RELEASE
        events.append("pinned")
        return SimpleNamespace(launch_executable=replacement)

    def restart(_argv, *, executable):
        assert executable == str(replacement)
        events.append("restarted")

    def serve_forever(*, cycle_maintenance, pin_served_release, reload_exec, reload_argv, **_):
        def replace():
            executable = pin_served_release(NEXT_RELEASE)
            with pytest.raises(session_relay_release.RelayReleaseError, match="returned"):
                reload_exec(reload_argv, executable=str(executable))

        cycle_maintenance()
        assert started.wait(timeout=TIMEOUT)
        pin_thread = Thread(target=replace, daemon=True)
        pin_thread.start()
        try:
            assert waiting_to_pin.wait(timeout=TIMEOUT)
            cycle_maintenance()
            assert events == []
        finally:
            release_follow.set()
            _join(pin_thread)
        # The successful pin keeps admission closed until the process switches.
        cycle_maintenance()
        assert events == ["follow complete", "pinned", "restarted"]

    monkeypatch.setattr(operator_cli_release_follow_worker, "Thread", FollowThread)
    monkeypatch.setattr(follow, "follow_release", follow_release)
    monkeypatch.setattr(session_relay_release_install, "pin_relay_release", pin)
    monkeypatch.setattr(session_relay_process_restart, "exec_relay_release", restart)
    monkeypatch.setattr(session_relay_daemon, "serve_forever", serve_forever)
    serve_release_daemon()
