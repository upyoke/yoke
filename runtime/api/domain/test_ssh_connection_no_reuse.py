"""Windows OpenSSH runs each host command without Unix socket multiplexing."""

import subprocess

import pytest

from yoke_harness import ssh_test_machine_transport as transport


@pytest.mark.windows_only(reason="Windows OpenSSH does not implement Unix ControlMaster sockets")
def test_windows_ssh_executes_repeated_commands_without_control_options(tmp_path, monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, argv[-1], "")

    monkeypatch.setattr(transport.subprocess, "run", run)
    monkeypatch.setattr(transport.SshTestMachineTransport, "_host_facts", lambda self: {
        "home": "/home/tester", "shell": "/bin/sh",
    }, raising=False)
    client = transport.SshTestMachineTransport(
        settings={"os": "linux", "host": "test-host", "user": "tester"},
        key_path=tmp_path / "key",
    )

    for command in ("first command", "second command"):
        result = client.run_remote_command(command)
        assert result.returncode == 0
        assert result.stdout == command

    assert [argv[-1] for argv in calls] == ["first command", "second command"]
    for argv in calls:
        assert argv[-2] == "tester@test-host"
        assert "-O" not in argv
        assert not any(option.lower().startswith("control") for option in argv)
