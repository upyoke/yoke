"""Transport-fake proof for Linux archives, tmux and OS adapter selection."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config.test_machine import validate_test_machine_settings
from yoke_harness.ssh_linux_baseline import (
    ABSENT_HOME_PATHS,
    _ARCHIVE_PROGRAM,
    archive_operation,
    capture_linux_golden,
)
from yoke_harness.ssh_linux_host_operations import SshLinuxHostOperations
from yoke_harness.ssh_linux_terminal import SCREENSHOT_DEFERRAL, diagnose_linux_terminal
from yoke_harness.test_machine_types import HostActionResult


SETTINGS = {
    "resource_name": "linux-lab",
    "host": "lab.invalid",
    "user": "tester",
    "os": "linux",
    "operating_notes": "",
}
PROBES = json.dumps({"probes": [{"name": "CLI signed in", "argv": ["/bin/true"]}]})


def test_linux_settings_refuse_root_and_unimplemented_os():
    assert validate_test_machine_settings(SETTINGS)["os"] == "linux"
    with pytest.raises(ValueError, match="linux_test_user_required"):
        validate_test_machine_settings({**SETTINGS, "user": "root"})
    with pytest.raises(ValueError, match="test_machine_os_unsupported.*macos, linux"):
        validate_test_machine_settings({**SETTINGS, "os": "windows"})
    with pytest.raises(ValueError, match="serving_floor_required"):
        validate_test_machine_settings(
            {key: value for key, value in SETTINGS.items() if key != "os"}
        )


def test_linux_facts_are_bounded_non_root_and_credentials_stay_out_of_argv(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {
                    "home": "/home/tester",
                    "shell": "/bin/bash",
                    "uid": 1000,
                    "os": "Linux",
                }
            ),
            "",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    control = SshLinuxHostOperations(
        settings=SETTINGS, key_path="/private/ssh-key", secret_values=("opaque-key",)
    )
    assert control.home == "/home/tester"
    assert control.secret_values == ("opaque-key",)
    assert "opaque-key" not in str(calls)
    assert "/private/ssh-key" in calls[0]


def test_linux_facts_refuse_root_before_any_restore(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {"home": "/root", "shell": "/bin/bash", "uid": 0, "os": "Linux"}
            ),
            "",
        ),
    )
    with pytest.raises(Exception, match="non-root"):
        SshLinuxHostOperations(settings=SETTINGS, key_path="/private/key")


def _archive_run(home: Path, golden: Path, operation: str):
    # This is the fake remote's interpreter; it only owns pytest's temp home.
    return subprocess.run(
        [sys.executable, "-c", _ARCHIVE_PROGRAM, operation, str(home), str(golden)],
        input=json.dumps(ABSENT_HOME_PATHS),
        text=True,
        capture_output=True,
        env={**os.environ, "HOME": str(home)},
        check=False,
    )


def test_archive_roundtrip_restores_credentials_preserves_ssh_and_proves_absence(
    tmp_path,
):
    if os.getuid() == 0:
        pytest.skip("archive fixture needs the declared non-root execution user")
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    (home / ".claude/.credentials.json").write_text("signed-in-state")
    (home / ".ssh").mkdir()
    (home / ".ssh/authorized_keys").write_text("original")
    golden = tmp_path / "golden"
    captured = _archive_run(home, golden, "capture")
    assert captured.returncode == 0, captured.stderr
    (home / ".claude/.credentials.json").write_text("expired")
    (home / ".ssh/authorized_keys").write_text("new-authorized-key")
    (home / ".yoke").mkdir()
    (home / ".yoke/config.json").write_text("residue")
    restored = _archive_run(home, golden, "reset")
    assert restored.returncode == 0, restored.stderr
    assert (home / ".claude/.credentials.json").read_text() == "signed-in-state"
    assert (home / ".ssh/authorized_keys").read_text() == "new-authorized-key"
    assert not (home / ".yoke").exists()
    assert json.loads(restored.stdout)["absent_paths"] == list(ABSENT_HOME_PATHS)


def test_golden_inside_home_refuses_before_deleting_residue(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "keep").write_text("untouched")
    result = _archive_run(home, home / "golden", "reset")
    assert result.returncode != 0
    assert (home / "keep").read_text() == "untouched"


def test_capture_probes_must_pass_before_archive_or_writes():
    calls = []
    control = SimpleNamespace(
        run_command=lambda *a, **kw: subprocess.CompletedProcess(a, 1, "", ""),
        _run=lambda *a, **kw: calls.append(a),
    )
    result = capture_linux_golden(control, "/var/lib/goldens/tester", PROBES)
    assert not result.ok and result.error_code == "baseline_probe_failed"
    assert not calls


def test_archive_operation_records_malformed_transport_receipt_as_named_failure():
    control = SimpleNamespace(
        home="/home/tester",
        _run=lambda *a, **kw: subprocess.CompletedProcess(a, 1, "unexpected", ""),
    )
    result = archive_operation(control, "reset", "/var/lib/goldens/tester")
    assert not result.ok and result.error_code == "linux_golden_operation_failed"
    assert result.evidence["recovery"]


def test_bridge_proves_transcript_and_records_screenshot_deferral():
    commands = []
    token_parts = []

    def run(command, **kw):
        argv = shlex.split(command)
        commands.append(argv)
        if "send-keys" in argv and "-l" in argv:
            # Capture the token from printf's two argv parts, never echo the command.
            text = argv[-1].split("; printf", 1)[0]
            parts = shlex.split(text)
            if parts[:2] == ["printf", "%s%s\\n"]:
                token_parts[:] = parts[2:]
        output = "".join(token_parts) + "\n" if "capture-pane" in argv else ""
        return subprocess.CompletedProcess(argv, 0, output, "")

    result = diagnose_linux_terminal(SimpleNamespace(_run=run))
    assert result.ok
    assert any(
        row.get("code") == SCREENSHOT_DEFERRAL and row["outcome"] == "deferred"
        for row in result.evidence["checks"]
    )
    assert any("kill-session" in argv for argv in commands)


def test_linux_baseline_dispatch_uses_linux_operations():
    from yoke_core.domain.host_baseline_operations import run_host_baseline

    requested = []
    control = SimpleNamespace(
        os="linux",
        reach_baseline=lambda name: (
            requested.append(name) or HostActionResult(True, {"os": "linux"})
        ),
    )
    result = run_host_baseline(control, "fresh-host")
    assert result.ok and requested == ["fresh-host"]
