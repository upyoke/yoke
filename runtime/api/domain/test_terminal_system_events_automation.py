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
            MISSING,
            "automation_missing:Terminal->System Events: (-1743)",
            diagnostics={"tcc_log": {"output": "pending consent"}},
        ),
    )
    host = ScriptedMacHost()

    result = execute_terminal_recipe(
        host,
        yoke_bin="yoke",
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
    assert (
        result.evidence["automation_diagnostics"]["tcc_log"]["output"]
        == "pending consent"
    )
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


def test_timeout_snapshots_process_and_tcc_before_stopping_tree(monkeypatch):
    import base64
    from types import SimpleNamespace
    from yoke_harness import ssh_mac_gui_session as gui
    from yoke_harness.ssh_mac_process_tree import ProcessTreeStop

    order = []
    ticks = iter((0, 16))
    monkeypatch.setattr(gui.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(
        gui, "open_terminal_app_window", lambda *a, **kw: SimpleNamespace(window_id=7)
    )
    monkeypatch.setattr(
        gui,
        "stop_process_tree",
        lambda *a: order.append("stop") or ProcessTreeStop(True),
    )
    monkeypatch.setattr(
        gui, "close_terminal_app_window", lambda *a, **kw: order.append("close") or True
    )
    monkeypatch.setattr(automation_probe, "read_terminal_window_count", lambda run: 2)

    def run(command, **kwargs):
        if "ps -o pid,etime,stat" in command:
            order.append("ps")
            assert kwargs["timeout"] == 5
            return _completed_output("PID ELAPSED STAT\n123 00:30 S")
        if "log show" in command:
            order.append("tcc")
            assert "--last 30s" in command and "com.apple.TCC" in command
            assert "pipefail" in command and "tail -c 8192" in command
            return _completed_output(
                "-----BEGIN PRIVATE KEY-----hidden-----END PRIVATE KEY----- "
                + "x" * 9000
            )
        if command.startswith("/usr/bin/base64"):
            return _completed_output(
                base64.b64encode(b"123").decode() if command.endswith(".pid") else ""
            )
        return _completed_output("")

    probe = automation_probe.terminal_system_events_automation(run)
    assert probe.error_code == TIMEOUT
    assert order == ["ps", "tcc", "stop", "close"]
    assert "123 00:30 S" in probe.diagnostics["system_events_process"]["output"]
    log = probe.diagnostics["tcc_log"]["output"]
    assert len(log) <= 512 and "hidden" not in log
    assert "[REDACTED]" in log
    assert automation_probe.AUTOMATION_PROBE_TIMEOUT_SECONDS == 15


def _completed_output(stdout):
    return subprocess.CompletedProcess([], 0, stdout, "")


def test_unavailable_timeout_diagnostics_keep_named_recovery(monkeypatch):
    monkeypatch.setattr(
        automation_probe, "run_terminal_app_command", lambda *a, **kw: _completed(124)
    )
    monkeypatch.setattr(automation_probe, "read_terminal_window_count", lambda run: 1)

    def unavailable(*a, **kw):
        raise TimeoutError("private exception detail")

    probe = automation_probe.terminal_system_events_automation(unavailable)
    assert probe.error_code == TIMEOUT
    for row in probe.diagnostics.values():
        assert row["reason"] == "terminal_automation_diagnostic_unavailable"
        assert "retry bridge-diagnose" in row["recovery"]
        assert "private exception detail" not in str(row)


def test_apple_event_timeout_keeps_diagnostics_before_window_cleanup(monkeypatch):
    from yoke_harness import ssh_mac_gui_session as gui

    order = []
    monkeypatch.setattr(
        gui,
        "_drive_window",
        lambda *a, **kw: _completed(1, "AppleEvent timed out (-1712)"),
    )
    monkeypatch.setattr(
        gui, "close_terminal_app_window", lambda *a, **kw: order.append("close") or True
    )
    monkeypatch.setattr(automation_probe, "read_terminal_window_count", lambda run: 1)

    def run(command, **kw):
        if "ps -o pid,etime,stat" in command:
            order.append("ps")
        if "log show" in command:
            order.append("tcc")
        return _completed_output("snapshot")

    result = automation_probe.terminal_system_events_automation(run)
    assert result.error_code == TIMEOUT
    assert order == ["ps", "tcc", "close"]
    assert result.diagnostics["tcc_log"]["output"] == "snapshot"
