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
    monkeypatch.setattr(transport, "scratch_root_candidates", lambda: (tmp_path,))
    monkeypatch.setattr(transport.SshTestMachineTransport, "_host_facts", lambda self: {
        "home": "/home/tester", "shell": "/bin/sh",
    }, raising=False)
    return transport.SshTestMachineTransport(
        settings={"os": "linux", "host": host, "user": user},
        key_path=tmp_path / key,
    )


@pytest.mark.posix_only(reason='requires Unix control sockets')
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


@pytest.mark.posix_only(reason='requires Unix control sockets')
def test_unusable_socket_directory_teaches_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "scratch_root_candidates", lambda: (tmp_path,))
    directory = tmp_path / f"ssh-{transport.os.getuid()}"
    directory.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(RuntimeError, match="host_control_ssh_socket_unavailable.*temp_root"):
        transport._control_socket("host", "user", tmp_path / "key")


@pytest.mark.posix_only(reason='requires Unix control sockets')
def test_long_socket_path_teaches_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(transport, "scratch_root_candidates", lambda: (tmp_path / ("x" * 90),))
    with pytest.raises(RuntimeError, match="host_control_ssh_socket_unavailable.*temp_root"):
        transport._control_socket("host", "user", tmp_path / "key")


@pytest.mark.posix_only(reason='requires Unix control sockets')
@pytest.mark.parametrize("diagnostic", transport._STALE_SOCKET_ERRORS)
def test_stale_master_warns_before_native_fallback_executes_once(tmp_path, monkeypatch, capsys, diagnostic):
    instance = control(tmp_path, monkeypatch)
    instance._control_path.touch()
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
    assert calls[0][0][1:3] == ["-O", "check"]
    assert calls[0][0][-1] == "tester@test-host"
    assert calls[1][0][-1] == "click once"
    assert "ControlMaster=auto" in calls[1][0]
    assert calls[1][1]["input"] == "payload"
    assert calls[1][1]["timeout"] <= 20
    assert "host_control_ssh_stale_socket" in capsys.readouterr().err


@pytest.mark.posix_only(reason='requires Unix control sockets')
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


@pytest.mark.posix_only(reason='requires Unix control sockets')
def test_native_fallback_result_is_never_replayed(tmp_path, monkeypatch):
    instance = control(tmp_path, monkeypatch)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 255, "", "mux_client_hello_exchange: broken")

    monkeypatch.setattr(subprocess, "run", run)
    assert instance._run("read").returncode == 255
    assert len(calls) == 1


@pytest.mark.posix_only(reason='requires Unix control sockets')
def test_live_master_check_does_not_execute_remote_command(tmp_path, monkeypatch, capsys):
    instance = control(tmp_path, monkeypatch)
    instance._control_path.touch()
    calls = []

    def run(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "receipt", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert instance._run("capture desktop").stdout == "receipt"
    assert len(calls) == 2
    assert calls[0][1:3] == ["-O", "check"]
    assert "capture desktop" not in calls[0]
    assert calls[1][-1] == "capture desktop"
    assert capsys.readouterr().err == ""


@pytest.mark.posix_only(reason='requires Unix control sockets')
def test_long_configured_root_uses_existing_short_scratch_candidate(tmp_path, monkeypatch):
    long_root = tmp_path / ("x" * 90)
    monkeypatch.setattr(transport, "scratch_root_candidates", lambda: (long_root, tmp_path))
    socket = transport._control_socket("host", "user", tmp_path / "key")
    assert socket.is_relative_to(tmp_path)
    assert not socket.is_relative_to(long_root)
    assert not long_root.exists()


@pytest.mark.parametrize("controller", ["darwin", "linux", "win32"])
def test_windows_target_never_creates_or_checks_master_on_any_controller(monkeypatch, controller):
    calls = []
    monkeypatch.setattr(transport, "_control_socket", lambda *a: pytest.fail("Windows target allocated a socket"))

    def facts(self):
        assert self._control_path is None
        assert self._run("one facts command", timeout=20).returncode == 0
        return {"home": r"C:\Users\qa", "shell": "powershell.exe"}

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "receipt", "")

    monkeypatch.setattr(transport.SshTestMachineTransport, "_host_facts", facts, raising=False)
    monkeypatch.setattr(subprocess, "run", run)
    with monkeypatch.context() as platform:
        platform.setattr(transport.sys, "platform", controller)
        instance = transport.SshTestMachineTransport(
            settings={"os": "windows", "host": "host", "user": "qa"}, key_path=Path("key"),
        )
        argv = instance._ssh_argv("command")
    assert len(calls) == 1 and "-O" not in calls[0]
    for option in ("ControlMaster=no", "ControlPersist=no", "ControlPath=none"):
        assert argv.count(option) == 1 and calls[0].count(option) == 1
    # SFTP receives precisely this base connection prefix, without a PS command.
    sftp = ["sftp", *argv[1:-2], "-b", "-", argv[-2]]
    assert all(option in sftp for option in ("ControlMaster=no", "ControlPersist=no", "ControlPath=none"))
    assert "ControlMaster=auto" not in argv and "ControlPersist=30" not in argv


def test_windows_explicit_policy_overrides_ambient_ssh_configuration(tmp_path, monkeypatch):
    import shutil

    if shutil.which("ssh") is None:
        pytest.skip("OpenSSH client not installed")
    instance = object.__new__(transport.SshTestMachineTransport)
    instance.os, instance._host, instance._user = "windows", "localhost", "qa"
    instance._key_path, instance._control_path, instance._host_key_options = tmp_path / "key", None, []
    config = tmp_path / "config"
    config.write_text("Host *\n  ControlMaster auto\n  ControlPersist 99\n  ControlPath ambient-master\n")
    argv = instance._ssh_argv("must not execute")
    result = subprocess.run([argv[0], "-G", "-F", str(config), *argv[1:-1]], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    effective = dict(line.split(" ", 1) for line in result.stdout.splitlines() if " " in line)
    assert effective["controlmaster"] == "false"
    assert effective["controlpersist"] == "no"
    assert effective.get("controlpath", "none") == "none"
