"""Installed-release restarts reuse the relay's existing drain and lock scope."""

import threading

from yoke_harness.session_relay import ServeOnceOutcome
from yoke_harness.session_relay_daemon import serve_forever
from yoke_harness.session_relay_schedule import relay_run_lock


def test_installed_release_change_drains_before_restart(tmp_path, capsys):
    steps = []
    started = threading.Event()
    finish = threading.Event()
    checks = iter((False, True))

    def settle():
        started.set()
        assert finish.wait(2)
        steps.append("settled")

    def cycle(*, dispatch_job, **kwargs):
        steps.append("poll")
        dispatch_job(settle, lambda reason: steps.append(reason))
        assert started.wait(2)
        return ServeOnceOutcome("dispatched", 1)

    def reload_check():
        changed = next(checks)
        if changed:
            finish.set()
        return changed

    def restart(argv, *, executable):
        assert argv is None and executable is None
        with relay_run_lock(tmp_path) as acquired:
            assert acquired
        steps.append("restart")

    outcome = serve_forever(
        state_dir=tmp_path,
        cycle=cycle,
        cycle_maintenance=lambda: steps.append("maintenance"),
        stop_after_cycles=2,
        idle_tick_seconds=0,
        drain_timeout_seconds=2,
        install_signals=False,
        reload_check=reload_check,
        reload_exec=restart,
    )

    assert steps == ["maintenance", "poll", "settled", "restart"]
    assert outcome.reason == "installed_release_changed"
    assert outcome.cycles == outcome.jobs_settled == 1
    assert "installed_release_changed" in capsys.readouterr().err


def test_daemon_without_release_check_keeps_polling(tmp_path):
    steps = []

    def cycle(**kwargs):
        steps.append("poll")
        return ServeOnceOutcome("active", 1)

    outcome = serve_forever(
        state_dir=tmp_path,
        cycle=cycle,
        cycle_maintenance=lambda: steps.append("maintenance"),
        stop_after_cycles=2,
        idle_tick_seconds=0,
        install_signals=False,
        reload_exec=lambda *args, **kwargs: steps.append("restart"),
    )

    assert steps == ["maintenance", "poll", "maintenance", "poll"]
    assert outcome.reason == "cycle_cap"
