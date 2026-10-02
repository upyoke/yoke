"""Timed-out host reads preserve safe partial evidence for their callers."""

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
