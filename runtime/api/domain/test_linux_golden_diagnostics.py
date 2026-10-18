"""Failed archive transport retains bounded-window evidence without replay."""

import json
from pathlib import Path
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness.ssh_linux_golden_diagnostics import run_golden_command
from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport


@pytest.mark.parametrize("exit_code", [0, 255, 124])
def test_golden_debug_and_journal_preserve_original_result(
    tmp_path, monkeypatch, exit_code
):
    from yoke_harness import ssh_linux_golden_diagnostics as diagnostics

    directory = tmp_path / "private-logs"
    directory.mkdir(mode=0o700)
    monkeypatch.setattr(diagnostics.tempfile, "mkdtemp", lambda **kw: str(directory))
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if "debug_log" in kwargs:
            kwargs["debug_log"].write_text(
                "debug1: Sending command: python -c '\nprivate program\n'\n"
                "debug1: Connection closed SECRET\n"
            )
            return subprocess.CompletedProcess([], exit_code, '{"ok":true}', "original")
        return subprocess.CompletedProcess(
            [], 1, "sshd event SECRET", "sudo denied SECRET"
        )

    result, evidence = run_golden_command(
        SimpleNamespace(_run=run, secret_values=("SECRET",)),
        "archive",
        input_text="input",
        timeout=1200,
    )
    assert result.returncode == exit_code and result.stderr == "original"
    assert len(calls) == 2 and calls[0][0] == "archive"
    journal = shlex.split(calls[1][0])
    assert journal[:3] == ["sudo", "-n", "journalctl"]
    assert journal[journal.index("--since") + 1] == evidence["started_at"]
    assert journal[journal.index("--until") + 1] == evidence["completed_at"]
    assert calls[1][1]["timeout"] == 20
    assert evidence["sshd_journal_exit_code"] == 1
    for key in ("ssh_client_log", "sshd_journal_log"):
        path = Path(evidence[key])
        assert path.stat().st_mode & 0o777 == 0o600
        assert (
            "SECRET" not in path.read_text()
            and "private program" not in path.read_text()
        )
    assert "Connection closed" in Path(evidence["ssh_client_log"]).read_text()
    assert "SECRET" not in json.dumps(evidence)


def test_existing_transport_directs_debug_to_private_file(tmp_path, monkeypatch):
    seen = []
    control = SimpleNamespace(_ssh_argv=lambda command: ["ssh", "target", command])
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: (
            seen.append(argv) or subprocess.CompletedProcess(argv, 0, "", "")
        ),
    )
    log = tmp_path / "ssh.log"
    SshTestMachineTransport._run(control, "archive", debug_log=log)
    assert seen == [["ssh", "-vvv", "-E", str(log), "target", "archive"]]
