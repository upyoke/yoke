"""Dashboard identity checks and named Windows port failures."""
from __future__ import annotations

import os
import socket

import pytest

from yoke_cli.config import universe_ui_daemon as daemon
from yoke_cli.config import universe_ui_daemon_state as state


def test_reused_pid_is_neither_reported_nor_stopped(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "profile with spaces"))
    state.write_record(pid=os.getpid(), host="127.0.0.1", port=8688,
                       env="local", supervised=False, process_start_time=1.0)
    monkeypatch.setattr(daemon.platform_process, "stop_group",
                        lambda *args: pytest.fail("must not stop a reused PID"))
    assert daemon.status()["running"] is False
    assert not state.record_path().exists()


def test_port_in_use_names_port_and_recovery():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(state.UiDaemonError, match="ui_port_unavailable") as refused:
            state.require_available_port("127.0.0.1", port)
        assert str(port) in str(refused.value)
        assert "--port PORT" in str(refused.value)


def test_hyper_v_reserved_port_names_cause(monkeypatch):
    class ReservedSocket:
        def __init__(self, *args):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def bind(self, address):
            raise PermissionError(10013, "forbidden by its access permissions")
    monkeypatch.setattr(state.socket, "socket", ReservedSocket)
    with pytest.raises(state.UiDaemonError, match="reserved by Windows/Hyper-V"):
        state.require_available_port("127.0.0.1", 8688)


def test_process_access_refusal_is_a_named_dashboard_error(monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("process access denied")
    monkeypatch.setattr(state.platform_process, "pid_alive", denied)
    with pytest.raises(state.UiDaemonError, match="ui_process_inspection_failed.*owner"):
        state.process_alive(42, 1.0)


def test_private_write_refusal_names_recovery(monkeypatch, tmp_path):
    def denied(*args):
        raise PermissionError("file locked")
    monkeypatch.setattr(state, "write_owner_private", denied)
    with pytest.raises(state.UiDaemonError, match="ui_private_write_failed.*handles"):
        state._write_private(tmp_path / "session-token", "not-a-live-token")


def test_state_directory_refusal_is_not_reported_as_stopped(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    def denied(*args):
        raise PermissionError("directory access denied")
    monkeypatch.setattr(state, "create_private_directory", denied)
    with pytest.raises(state.UiDaemonError, match="ui_state_unavailable.*owner access"):
        daemon.status()


def test_startup_cleanup_refusal_never_claims_nothing_is_running(monkeypatch):
    from types import SimpleNamespace
    def denied(*args):
        raise PermissionError("cannot stop child")
    monkeypatch.setattr(daemon.platform_process, "stop_group", denied)
    with pytest.raises(state.UiDaemonError, match="ui_start_cleanup_failed.*42"):
        daemon._tear_down(supervised=False, child=SimpleNamespace(pid=42))
