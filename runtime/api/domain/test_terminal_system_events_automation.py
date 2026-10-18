"""A missing Terminal -> System Events grant fails fast and by name."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from runtime.api.domain.machine_qa_terminal_recipe_test_support import recipe
from runtime.api.domain.scripted_mac_host_test_support import ScriptedMacHost
from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_BRIDGE_RECOVERY,
    TERMINAL_SYSTEM_EVENTS_AUTOMATION_FAILED_ERROR_CODE as FAILED,
    TERMINAL_SYSTEM_EVENTS_AUTOMATION_MISSING_ERROR_CODE as MISSING,
    TERMINAL_SYSTEM_EVENTS_AUTOMATION_TIMEOUT_ERROR_CODE as TIMEOUT,
    TERMINAL_WINDOW_ACCUMULATION_ERROR_CODE as ACCUMULATION,
)
from yoke_core.domain.ssh_mac_terminal_recipe import execute_terminal_recipe
from yoke_harness import ssh_mac_terminal_automation_probe as automation_probe
from yoke_harness.ssh_mac_terminal_automation_probe import TerminalAutomationProbe
from yoke_harness.ssh_mac_terminal_window_close import close_terminal_app_window


def _completed(returncode: int, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(("osascript",), returncode, "", stderr)


def test_probe_runs_inside_terminal_with_a_short_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    def fake_command(_run, **kwargs):
        calls.append(kwargs)
        return _completed(1, "execution error: Not authorised (-1743)")

    monkeypatch.setattr(automation_probe, "run_terminal_app_command", fake_command)

    probe = automation_probe.terminal_system_events_automation(object())

    assert not probe.ok
    assert probe.error_code == MISSING
    assert probe.detail.startswith("automation_missing:Terminal->System Events: ")
    assert "-1743" in probe.detail
    assert calls[0]["timeout"] == automation_probe.AUTOMATION_PROBE_TIMEOUT_SECONDS
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
        lambda _run: TerminalAutomationProbe(
            MISSING, "automation_missing:Terminal->System Events: (-1743)"
        ),
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
    assert "-1743" in result.evidence["automation_detail"]
    assert "Privacy & Security > Automation" in result.evidence["recovery"]
    assert not any("/tmp/yoke-qa-" in c for c in host.commands)


@pytest.mark.parametrize(
    ("answer", "closed"),
    [("closed\n", True), ("open\n", False), ("", False)],
)
def test_window_close_kills_its_tty_processes_and_reports_the_outcome(
    answer: str, closed: bool
) -> None:
    commands: list[str] = []

    def run(command: str, **_kwargs) -> subprocess.CompletedProcess:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, answer, "")

    assert close_terminal_app_window(run, window_id=445) is closed

    script = commands[0]
    assert script.index("pkill -KILL -t") < script.index("close window id 445")
    # The tty list is read inside the Terminal block and coerced outside it: a
    # tab reference does not coerce to text, and that error (-1700) aborted
    # the script before the close on every command.
    assert "set ttyPaths to tty of every tab of window id 445" in script
    assert "(ttyPath as text)" in script
    assert script.index("end tell") < script.index("do shell script")
    assert "if visible of window id 445" in script


def test_window_close_without_a_window_has_nothing_to_close() -> None:
    assert close_terminal_app_window(lambda *_a, **_k: None, window_id=None)


def _probe(
    monkeypatch: pytest.MonkeyPatch,
    result: subprocess.CompletedProcess,
    windows: int | None,
) -> TerminalAutomationProbe:
    monkeypatch.setattr(
        automation_probe, "run_terminal_app_command", lambda _run, **_kw: result
    )
    monkeypatch.setattr(
        automation_probe, "read_terminal_window_count", lambda _run: windows
    )
    return automation_probe.terminal_system_events_automation(object())


def test_a_timeout_among_accumulated_windows_is_named_as_accumulation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 241 windows left by earlier runs made every command inside Terminal time
    # out while the grant was allowed; that is not a missing grant.
    probe = _probe(monkeypatch, _completed(124, "Terminal.app command timed out"), 241)

    assert probe.error_code == ACCUMULATION
    assert probe.detail.startswith("terminal_window_accumulation:241")
    assert probe.terminal_windows == 241
    assert "yoke test-machine reset" in TERMINAL_BRIDGE_RECOVERY[ACCUMULATION]


@pytest.mark.parametrize(
    ("result", "windows"),
    [
        (_completed(124, "Terminal.app command timed out"), 2),
        (_completed(124, "Terminal.app command timed out"), None),
        (_completed(1, "execution error: AppleEvent timed out. (-1712)"), 1),
    ],
)
def test_a_timeout_without_accumulation_is_not_called_a_denial(
    monkeypatch: pytest.MonkeyPatch,
    result: subprocess.CompletedProcess,
    windows: int | None,
) -> None:
    probe = _probe(monkeypatch, result, windows)

    assert probe.error_code == TIMEOUT
    assert probe.detail.startswith("automation_timeout:Terminal->System Events: ")
    assert probe.terminal_windows == windows


def test_another_failure_keeps_its_exit_code_and_is_not_a_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = _probe(monkeypatch, _completed(125, "Terminal.app launch failed"), None)

    assert probe.error_code == FAILED
    assert "exit 125" in probe.detail
