"""Native Windows browser-owner queries never signal a process."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_contracts import windows_process_snapshot as windows
from yoke_contracts import process_ancestry
from yoke_core.domain import browser_client as core_client
from yoke_harness import browser_client


def kernel_api(*, handle=123, wait=windows.WAIT_TIMEOUT, readable=True):
    def times(handle, creation, exited, kernel, user):
        creation._obj.dwHighDateTime = 7
        creation._obj.dwLowDateTime = 11
        return readable

    return SimpleNamespace(
        OpenProcess=Mock(return_value=handle),
        WaitForSingleObject=Mock(return_value=wait),
        GetProcessTimes=Mock(side_effect=times),
        CloseHandle=Mock(),
    )


def test_native_creation_token_is_stable_and_closes_its_handle():
    api = kernel_api()
    expected = str((7 << 32) | 11)
    assert windows.process_start_time(42, api=api) == expected
    api.OpenProcess.assert_called_once_with(0x101000, False, 42)
    api.WaitForSingleObject.assert_called_once_with(123, 0)
    api.CloseHandle.assert_called_once_with(123)


@pytest.mark.parametrize("wait", [0, 0xFFFFFFFF])
def test_exited_or_unreadable_process_is_not_live(wait):
    api = kernel_api(wait=wait)
    assert windows.process_start_time(42, api=api) is None
    api.GetProcessTimes.assert_not_called()
    api.CloseHandle.assert_called_once_with(123)


def test_absent_process_has_no_handle_to_close():
    api = kernel_api(handle=0)
    assert windows.process_start_time(42, api=api) is None
    api.CloseHandle.assert_not_called()


def test_creation_query_failure_still_closes_handle():
    api = kernel_api(readable=False)
    assert windows.process_start_time(42, api=api) is None
    api.CloseHandle.assert_called_once_with(123)


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


def test_central_process_owner_routes_native_windows_queries(monkeypatch):
    with monkeypatch.context() as patched:
        patched.setattr(process_ancestry.sys, "platform", "win32")
        patched.setattr(windows, "process_start_time", lambda pid: f"created:{pid}")
        assert process_ancestry.process_start_time(42) == "created:42"


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


def test_unavailable_native_query_returns_no_owner_token(monkeypatch):
    def unavailable():
        raise OSError("process query unavailable")

    monkeypatch.setattr(windows, "_kernel32", unavailable)
    assert windows.process_start_time(42) is None
