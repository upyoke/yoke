"""Host commands share a private master and never replay ambiguous failures."""

import subprocess
from pathlib import Path
import tempfile

import pytest

from yoke_harness import ssh_test_machine_transport as transport


@pytest.fixture
def tmp_path():
    # Exercise real Unix socket path limits independently of pytest's long root.
    with tempfile.TemporaryDirectory(prefix="ssh-test-", dir="/tmp") as root:
        yield Path(root)


def control(tmp_path, monkeypatch, *, host="test-host", user="tester", key="key"):
    monkeypatch.setattr(transport, "effective_temp_root", lambda: str(tmp_path))
    monkeypatch.setattr(transport.SshTestMachineTransport, "_host_facts", lambda self: {
        "home": "/home/tester", "shell": "/bin/sh",
    }, raising=False)
    return transport.SshTestMachineTransport(
        settings={"os": "linux", "host": host, "user": user},
        key_path=tmp_path / key,
    )


def test_private_socket_shared_across_calls_and_transport_instances(tmp_path, monkeypatch):
    first = control(tmp_path, monkeypatch)
    second = control(tmp_path, monkeypatch)
    assert first._control_path == second._control_path
    assert first._control_path.is_relative_to(tmp_path)
    assert first._control_path.parent.stat().st_mode & 0o777 == 0o700
    for command in ("read display", "capture screenshot", "click"):
        argv = first._ssh_argv(command)
        assert "ControlMaster=auto" in argv
        assert "ControlPersist=30" in argv
        assert f"ControlPath={first._control_path}" in argv
        assert argv[-1] == command
    for settings in ({"host": "other"}, {"user": "other"}, {"key": "other"}):
        assert control(tmp_path, monkeypatch, **settings)._control_path != first._control_path


def test_unusable_socket_directory_teaches_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "effective_temp_root", lambda: str(tmp_path))
    directory = tmp_path / f"ssh-{transport.os.getuid()}"
    directory.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(RuntimeError, match="host_control_ssh_socket_unavailable.*temp_root"):
        transport._control_socket("host", "user", tmp_path / "key")


def test_long_socket_path_teaches_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "effective_temp_root", lambda: str(tmp_path / ("x" * 90)))
    with pytest.raises(RuntimeError, match="host_control_ssh_socket_unavailable.*temp_root"):
        transport._control_socket("host", "user", tmp_path / "key")


@pytest.mark.parametrize("diagnostic", transport._STALE_SOCKET_ERRORS)
def test_stale_master_retries_once_fresh_with_warning(tmp_path, monkeypatch, capsys, diagnostic):
    instance = control(tmp_path, monkeypatch)
    calls = []

    def run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 255, "", diagnostic + " failed")
        return subprocess.CompletedProcess(argv, 0, "receipt", "")

    monkeypatch.setattr(subprocess, "run", run)
    result = instance._run("click once", input_text="payload", timeout=20)
    assert result.returncode == 0 and result.stdout == "receipt"
    assert len(calls) == 2
    assert calls[1][0][1:5] == ["-o", "ControlMaster=no", "-o", "ControlPath=none"]
    assert calls[1][1]["input"] == "payload"
    assert calls[1][1]["timeout"] <= calls[0][1]["timeout"]
    assert "host_control_ssh_stale_socket" in result.stderr
    assert "host_control_ssh_stale_socket" in capsys.readouterr().err


@pytest.mark.parametrize("code,diagnostic", [
    (255, "Connection reset by peer"),
    (255, "mux_client_read_packet: read header failed: Broken pipe"),
    (1, "remote command failed"),
    (0, ""),
])
def test_ambiguous_disconnects_and_remote_failures_never_replay(tmp_path, monkeypatch, code, diagnostic):
    instance = control(tmp_path, monkeypatch)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, code, "output", diagnostic)

    monkeypatch.setattr(subprocess, "run", run)
    result = instance._run("change host state")
    assert len(calls) == 1
    assert result.returncode == code and result.stderr == diagnostic


def test_second_stale_failure_is_not_retried(tmp_path, monkeypatch):
    instance = control(tmp_path, monkeypatch)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 255, "", "mux_client_hello_exchange: broken")

    monkeypatch.setattr(subprocess, "run", run)
    assert instance._run("read").returncode == 255
    assert len(calls) == 2
