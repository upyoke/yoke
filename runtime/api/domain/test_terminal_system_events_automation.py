"""A missing Terminal -> System Events grant fails fast and by name."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from runtime.api.domain.machine_qa_terminal_recipe_test_support import recipe
from runtime.api.domain.scripted_mac_host_test_support import ScriptedMacHost
from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_SYSTEM_EVENTS_AUTOMATION_MISSING_ERROR_CODE as MISSING,
)
from yoke_core.domain.ssh_mac_terminal_recipe import execute_terminal_recipe
from yoke_harness import ssh_mac_gui_session
from yoke_harness.ssh_mac_terminal_app import close_terminal_app_window


def _completed(returncode: int, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(("osascript",), returncode, "", stderr)


def test_probe_runs_inside_terminal_with_a_short_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    def fake_command(_run, **kwargs):
        calls.append(kwargs)
        return _completed(1, "execution error: Not authorised (-1743)")

    monkeypatch.setattr(ssh_mac_gui_session, "run_terminal_app_command", fake_command)

    ok, detail = ssh_mac_gui_session.terminal_system_events_automation(object())

    assert not ok
    assert detail.startswith("automation_missing:Terminal->System Events: ")
    assert "-1743" in detail
    assert calls[0]["timeout"] == ssh_mac_gui_session.AUTOMATION_PROBE_TIMEOUT_SECONDS
    assert calls[0]["argv"][-1] == (
        'tell application "System Events" to count processes'
    )


def test_terminal_case_refuses_before_opening_its_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_terminal_app_recipe."
        "terminal_system_events_automation",
        lambda _run: (False, "automation_missing:Terminal->System Events: timed out"),
    )
    host = ScriptedMacHost()

    result = execute_terminal_recipe(
        host,
        upload_bytes=lambda *_args, **_kwargs: True,
        entry_surface="yoke setup",
        required_completion="done",
        config=recipe(mode="terminal"),
        evidence_parent=tmp_path,
        secret_values=(),
    )

    assert not result.ok
    assert result.error_code == MISSING
    assert "timed out" in result.evidence["automation_detail"]
    assert "Privacy & Security > Automation" in result.evidence["recovery"]
    assert not any("/tmp/yoke-qa-" in c for c in host.commands)


def test_window_close_kills_its_tty_processes_before_closing() -> None:
    commands: list[str] = []

    def run(command: str, **_kwargs) -> subprocess.CompletedProcess:
        commands.append(command)
        return _completed(0)

    close_terminal_app_window(run, window_id=445)

    script = commands[0]
    assert script.index("pkill -KILL -t") < script.index("close window id 445")
    assert "tty of every tab of window id 445" in script
