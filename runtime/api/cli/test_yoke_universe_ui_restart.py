"""Dashboard replacement preserves the running machine's serving identity."""

import os
import sys
import subprocess

import pytest

from yoke_cli.commands import universe_ui
from yoke_cli.config import universe_ui_daemon as daemon
from yoke_cli.config import universe_ui_daemon_state as state
from yoke_cli.config import universe_ui_launchd as launchd
from runtime.api.cli.yoke_universe_ui_daemon_test_support import (
    CHILD_SCRIPT,
    _free_port,
)


@pytest.fixture(autouse=True)
def isolated_machine(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    monkeypatch.setattr(launchd, "supported", lambda: False)
    monkeypatch.setattr(launchd, "agent_installed", lambda: False)
    monkeypatch.setattr(launchd, "remove_agent", lambda: False)


def test_real_detached_dashboard_is_replaced_and_bookmark_survives(monkeypatch):
    monkeypatch.setattr(
        launchd,
        "child_command",
        lambda *, host, port, env: [
            sys.executable,
            "-c",
            CHILD_SCRIPT,
            host,
            str(port),
            env,
        ],
    )
    children = []
    original_popen = subprocess.Popen
    original_alive = daemon.process_alive

    def spawn(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        children.append(child)
        return child

    def alive(pid):
        # A real supervisor reaps its children; retain the fixture supervisor.
        for child in children:
            child.poll()
        return original_alive(pid)

    monkeypatch.setattr(daemon.subprocess, "Popen", spawn)
    monkeypatch.setattr(daemon, "process_alive", alive)
    first = daemon.up(host="127.0.0.1", port=_free_port(), env="saved-universe")
    try:
        assert daemon.restart_running() == {"restarted": True}
        second = daemon.status()
        assert second["pid"] != first["pid"]
        assert not state.process_alive(first["pid"])
        assert second["serving"] is True
        for key in ("host", "port", "env", "private_url"):
            assert second[key] == first[key]
    finally:
        daemon.down()


@pytest.mark.parametrize("stale", [False, True])
def test_absent_or_stale_dashboard_stays_stopped(monkeypatch, stale):
    if stale:
        state.write_record(
            pid=123456, host="127.0.0.1", port=8688, env="saved", supervised=False
        )
    monkeypatch.setattr(daemon, "process_alive", lambda pid: False)
    monkeypatch.setattr(daemon, "up", lambda **kw: pytest.fail("must stay stopped"))
    assert daemon.restart_running() == {"restarted": False}
    assert not state.record_path().exists()
    assert not state.token_path().exists()


def test_stop_failure_retains_identity_and_teaches_recovery(monkeypatch):
    state.write_record(
        pid=os.getpid(), host="127.0.0.1", port=8688, env="saved", supervised=False
    )
    monkeypatch.setattr(daemon, "_terminate", lambda pid: None)
    monkeypatch.setattr(daemon, "up", lambda **kw: pytest.fail("old process survives"))
    with pytest.raises(
        state.UiDaemonError, match="ui_restart_stop_failed.*yoke ui down"
    ):
        daemon.restart_running()
    assert state.read_record().pid == os.getpid()


def test_start_failure_names_saved_settings_and_cli_fails(monkeypatch, capsys):
    state.write_record(
        pid=123456, host="127.0.0.1", port=8765, env="saved", supervised=False
    )
    alive = iter([True, False])
    monkeypatch.setattr(daemon, "process_alive", lambda pid: next(alive))
    monkeypatch.setattr(daemon, "down", state.clear_record)

    def fail(**kwargs):
        raise state.UiDaemonError("port occupied")

    monkeypatch.setattr(daemon, "up", fail)
    assert universe_ui.ui_restart_running(["--json"]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert "ui_restart_start_failed" in captured.err
    assert (
        "yoke --env saved ui up --host 127.0.0.1 --port 8765 --no-browser"
        in captured.err
    )


def test_restart_receipt_never_prints_private_url(monkeypatch, capsys):
    monkeypatch.setattr(daemon, "restart_running", lambda: {"restarted": True})
    assert universe_ui.ui_restart_running(["--json"]) == 0
    assert capsys.readouterr().out.strip() == '{"ok": true, "restarted": true}'


def test_invalid_record_blocks_success_instead_of_reporting_stopped():
    state.record_path().write_text("broken json")
    with pytest.raises(state.UiDaemonError, match="ui_restart_identity_invalid"):
        daemon.restart_running()
    assert state.record_path().read_text() == "broken json"
