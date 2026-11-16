"""Native Windows browser-owner queries never signal a process."""

from unittest.mock import Mock

import pytest

from yoke_contracts import process_ancestry
from yoke_core.domain import browser_client as core_client
from yoke_harness import browser_client


@pytest.mark.parametrize("client", [browser_client, core_client])
def test_windows_daemon_liveness_uses_native_query_without_os_kill(monkeypatch, client):
    state = client.DaemonState(pid=42)
    with monkeypatch.context() as patched:
        patched.setattr(client.sys, "platform", "win32")
        patched.setattr(process_ancestry, "process_start_time", lambda pid: "created")
        kill = Mock(
            side_effect=AssertionError("os.kill is not a Windows liveness probe")
        )
        patched.setattr(client.os, "kill", kill)
        assert client.daemon_running(state)
        kill.assert_not_called()


@pytest.mark.parametrize("client", [browser_client, core_client])
def test_windows_private_shutdown_uses_supported_termination(
    monkeypatch, tmp_path, client
):
    import signal
    import time

    state = client.DaemonState(pid=42)
    state_path = tmp_path / "state.json"
    with monkeypatch.context() as patched:
        patched.setattr(client.sys, "platform", "win32")
        patched.setattr(client, "_state_file_path", lambda *a: state_path)
        patched.setattr(client.DaemonState, "load", lambda *a: state)
        patched.setattr(client, "daemon_running", lambda *a: True)
        patched.setattr(client, "daemon_request", Mock(return_value={}))
        patched.setattr(time, "sleep", lambda *a: None)
        kill = Mock()
        patched.setattr(client.os, "kill", kill)
        assert client.daemon_stop(profile_dir="private-check") == "stopped"
        kill.assert_called_once_with(42, signal.SIGTERM)


@pytest.mark.parametrize("client", [browser_client, core_client])
def test_private_shutdown_does_not_signal_a_pid_reused_during_stop(
    monkeypatch, tmp_path, client
):
    state = client.DaemonState(pid=42)
    tokens = iter(["original", "replacement"])
    monkeypatch.setattr(
        process_ancestry, "process_start_time", lambda pid: next(tokens)
    )
    monkeypatch.setattr(client, "_state_file_path", lambda *a: tmp_path / "state.json")
    monkeypatch.setattr(client.DaemonState, "load", lambda *a: state)
    monkeypatch.setattr(client, "daemon_running", lambda *a: True)
    stop_request = Mock(return_value={})
    monkeypatch.setattr(client, "daemon_request", stop_request)
    kill = Mock()
    monkeypatch.setattr(client.os, "kill", kill)
    assert (
        client.daemon_stop(
            profile_dir="private-check", expected_process_start="original"
        )
        == "stopped"
    )
    stop_request.assert_called_once()
    kill.assert_not_called()
