"""Legacy login-probe failures remain visible alongside healthy contexts."""

import json
import subprocess

import pytest

from yoke_cli.commands.adapters import path_doctor as cli
from yoke_cli.config import path_doctor as doctor


@pytest.mark.parametrize("failure", ["timeout", "unavailable", "failed"])
@pytest.mark.parametrize("context", ["login", "ssh"])
def test_probe_failure_is_reported_without_claiming_path_is_missing(
    tmp_path, monkeypatch, capsys, failure, context,
):
    expected = str(tmp_path / "bin" / "yoke")

    def probe(command, **kwargs):
        assert kwargs["timeout"] == 10
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 10)
        if failure == "unavailable":
            raise OSError("cannot start shell")
        return subprocess.CompletedProcess(command, 1, "", "startup failed")

    monkeypatch.setattr(doctor.terminal_detached_process, "run", probe)
    resolved = doctor._verify_shell(
        "-lic", "bash", env={"HOME": str(tmp_path), "PATH": "/bin"},
    )
    reason = {
        "timeout": "shell_probe_timeout", "unavailable": "shell_probe_unavailable",
        "failed": "shell_probe_failed",
    }[failure]
    assert all(row.path is None and row.error == reason for row in resolved)
    healthy = [doctor.ToolResolution("yoke", expected)]
    diagnosis = doctor.PathDiagnosis(
        current_shell="bash", tool_bin_dir=str(tmp_path / "bin"),
        current_on_path=True, current_resolved=[doctor.ToolResolution("yoke", expected)],
        startup_file=str(tmp_path / ".profile"), future_adds_bin=True,
        managed_block_present=True,
        future_resolved=resolved if context == "login" else healthy, needs_fix=True,
        login_needs_fix=context == "login", preferred_yoke_path=expected,
        ssh_startup_file=str(tmp_path / ".bashrc"),
        ssh_resolved=resolved if context == "ssh" else healthy,
        ssh_needs_fix=context == "ssh",
        contexts=tuple({"shell": "bash", "context": context,
                        "resolved": {"yoke": expected}, "needs_fix": False,
                        "reason": "", "recovery": ""}
                       for context in ("login", "interactive", "non-login", "ssh")),
    )
    monkeypatch.setattr(doctor, "diagnose", lambda: diagnosis)
    monkeypatch.setattr(doctor, "update_shell", lambda: "already configured")
    for command, args in ((cli.path_check, []), (cli.path_fix, ["--yes"]),
                          (cli.path_verify, [])):
        assert command(args) == 1
        output = capsys.readouterr().out
        label = "future yoke" if context == "login" else "ssh yoke"
        assert f"{label:14}: {reason}; expected {expected}" in output
        startup = ".profile" if context == "login" else ".bashrc"
        assert f"Inspect {tmp_path / startup} and files it sources" in output
        assert "Fix the shell startup failure" in output
        assert "PATH verified." not in output
        for row in ("login", "interactive", "non-login", "ssh"):
            assert f"bash {row}: ok; yoke -> {expected}" in output
        assert command([*args, "--json"]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["probe_errors"][context]["yoke"] == reason
