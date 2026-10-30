"""Release probes retain the refusal that prevented verification."""

import json
import subprocess

import pytest

from runtime.api.tools.verify_install_advice import read_served_command


@pytest.mark.parametrize("exit_code", [0, 1])
def test_failed_envelope_keeps_reason_and_recovery(monkeypatch, capsys, exit_code):
    error = {
        "code": "setup_checklist_incomplete",
        "message": "Project demo needs checklist rows",
        "recovery_hint": "yoke onboard checklist init --project demo",
    }
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            exit_code,
            json.dumps({"success": False, "error": error}),
            "CLI context",
        ),
    )
    with pytest.raises(SystemExit, match="Repair the reported activation error"):
        read_served_command("stage")
    captured = capsys.readouterr().err
    assert "setup_checklist_incomplete" in captured
    assert "yoke onboard checklist init --project demo" in captured
    assert "CLI context" in captured
    assert "Traceback" not in captured


def test_non_json_failure_keeps_stderr(monkeypatch, capsys):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            2,
            "",
            "connection_unavailable: restore the stage connection",
        ),
    )
    with pytest.raises(SystemExit):
        read_served_command("stage")
    assert (
        "connection_unavailable: restore the stage connection"
        in capsys.readouterr().err
    )


def test_success_returns_served_command(monkeypatch):
    command = "curl -fsSL https://distribution.example/install | sh"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            json.dumps({"success": True, "result": {"install_command": command}}),
            "",
        ),
    )
    assert read_served_command("stage") == command


def test_timeout_is_named_without_traceback(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 60)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(SystemExit, match="install_advice_read_unavailable"):
        read_served_command("stage")
