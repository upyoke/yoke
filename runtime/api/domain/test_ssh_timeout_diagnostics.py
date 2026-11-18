"""SSH host reads: safe partial evidence on timeout, and a closed stdin without input."""

import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport


@pytest.mark.parametrize("as_bytes", [False, True])
def test_ssh_timeout_retains_partial_output_without_registered_secrets(
    monkeypatch, as_bytes
):
    secret = "registered-machine-secret"
    stdout = "unfinished query " + secret
    stderr = "Preparing modules " + secret + "x" * 2000
    if as_bytes:
        stdout, stderr = stdout.encode(), stderr.encode()

    def run(argv, **kwargs):
        assert kwargs["input"] == "framed command\n"
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"], stdout, stderr)

    monkeypatch.setattr(subprocess, "run", run)
    control = SimpleNamespace(
        secret_values=(secret,), _ssh_argv=lambda command: ["ssh", command]
    )
    result = SshTestMachineTransport._run(
        control, "read session state", input_text="framed command\n", timeout=45
    )
    assert result.returncode == 124
    assert result.stdout == "unfinished query [REDACTED]"
    assert result.stderr.startswith(
        "host_control subprocess timed out: Preparing modules [REDACTED]"
    )
    assert secret not in result.stderr and len(result.stderr) < 600


def test_a_command_without_input_gets_a_closed_stdin(monkeypatch):
    """An inherited open stdin makes `codex exec` wait for EOF over SSH."""
    calls = []

    def run(argv, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    control = SimpleNamespace(secret_values=(), _ssh_argv=lambda command: ["ssh", command])
    SshTestMachineTransport._run(control, "codex exec --json 'Reply exactly OK.'")
    SshTestMachineTransport._run(control, "cat", input_text="framed\n")
    assert calls[0]["stdin"] is subprocess.DEVNULL and "input" not in calls[0]
    assert calls[1]["input"] == "framed\n" and "stdin" not in calls[1]
