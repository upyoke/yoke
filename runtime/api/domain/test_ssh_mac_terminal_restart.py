"""A test-machine reset quits Terminal first and relaunches it once restored."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_harness import ssh_mac_transport
from yoke_harness.ssh_mac_terminal_restart import (
    RELAUNCH_COMMAND,
    TERMINAL_PROBE_FAILED,
    TERMINAL_QUIT_NOT_PROVED,
    TERMINAL_RELAUNCH_FAILED,
    quit_terminal_app,
    relaunch_terminal_app,
)
from yoke_harness.ssh_mac_transport import SshMacTransport
from yoke_harness.test_machine_types import HostActionResult


def _done(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class TerminalHost:
    """Terminal with *windows* open that a quit, or a kill, may stop."""

    def __init__(
        self,
        *,
        running: bool = True,
        windows: int = 241,
        quits: bool = True,
        dies_when_killed: bool = True,
        pgrep_rc: int | None = None,
    ) -> None:
        self.running, self.windows = running, windows
        self.quits, self.dies_when_killed = quits, dies_when_killed
        self.pgrep_rc = pgrep_rc
        self.commands: list[str] = []

    def __call__(self, command: str, *, timeout: int = 60) -> SimpleNamespace:
        self.commands.append(command)
        if command.startswith("kill_tree()"):
            self.running = not self.dies_when_killed
            return _done(0)
        if "to quit" in command:
            # A window still running a command answers quit with a sheet.
            self.running = not self.quits
            return _done(0 if self.quits else 1, stderr="AppleEvent timed out")
        if "count windows" in command:
            return _done(0, f"{self.windows}\n")
        if "while" in command:
            return _done(1 if self.running else 0)
        if self.pgrep_rc is not None:
            return _done(self.pgrep_rc, stderr="ssh: connection reset")
        return _done(0 if self.running else 1)


def test_a_stopped_terminal_needs_no_quit() -> None:
    host = TerminalHost(running=False)

    result = quit_terminal_app(host, "tester")

    assert result.ok
    assert result.evidence["terminal_quit"] == {"quit": "not_running"}
    assert len(host.commands) == 1


def test_terminal_that_quits_is_not_killed() -> None:
    host = TerminalHost()

    result = quit_terminal_app(host, "tester")

    assert result.ok
    assert result.evidence["terminal_quit"] == {
        "windows_before_quit": 241,
        "quit": "graceful",
    }
    assert not any(c.startswith("kill_tree()") for c in host.commands)


def test_a_quit_held_by_a_sheet_kills_the_window_processes_then_terminal() -> None:
    host = TerminalHost(quits=False)

    result = quit_terminal_app(host, "tester")

    assert result.ok
    assert result.evidence["terminal_quit"]["quit"] == "forced"
    kill = next(c for c in host.commands if c.startswith("kill_tree()"))
    assert "/usr/bin/pgrep -P" in kill
    assert "/bin/kill -KILL" in kill
    assert "/usr/bin/pgrep -x -u tester Terminal" in kill


def test_terminal_surviving_the_kill_refuses_with_a_console_recovery() -> None:
    host = TerminalHost(quits=False, dies_when_killed=False)

    result = quit_terminal_app(host, "tester")

    assert not result.ok
    assert result.error_code == TERMINAL_QUIT_NOT_PROVED
    assert "Quit Terminal at the host console" in result.evidence["recovery"]


def test_an_unreadable_process_table_is_not_taken_as_stopped() -> None:
    result = quit_terminal_app(TerminalHost(pgrep_rc=255), "tester")

    assert not result.ok
    assert result.error_code == TERMINAL_PROBE_FAILED
    assert result.evidence["terminal_quit"]["exit_code"] == 255


def test_relaunch_skips_saved_windows_and_waits_for_the_first_window() -> None:
    commands: list[str] = []

    def run(command: str, *, timeout: int = 60) -> SimpleNamespace:
        commands.append(command)
        return _done(0, "1\n" if "count windows" in command else "")

    result = relaunch_terminal_app(run)

    assert result.ok
    assert result.evidence["terminal_relaunch"] == {"terminal_windows": 1}
    assert commands[0] == RELAUNCH_COMMAND
    assert "-ApplePersistenceIgnoreState YES" in RELAUNCH_COMMAND


@pytest.mark.parametrize(
    ("open_result", "wait_result", "expected"),
    [
        (_done(1, stderr="LSOpenURLsWithRole() failed"), None, "stderr"),
        (_done(0), _done(1, "0\n"), "terminal_windows"),
    ],
)
def test_relaunch_without_a_window_fails_by_name(
    open_result, wait_result, expected
) -> None:
    def run(command: str, *, timeout: int = 60) -> SimpleNamespace:
        return open_result if command == RELAUNCH_COMMAND else wait_result

    result = relaunch_terminal_app(run)

    assert not result.ok
    assert result.error_code == TERMINAL_RELAUNCH_FAILED
    assert expected in result.evidence["terminal_relaunch"]
    assert "bridge-diagnose" in result.evidence["recovery"]


def _reset(monkeypatch: pytest.MonkeyPatch, **outcomes: HostActionResult):
    steps: list[str] = []

    def step(name: str):
        def run(*_args, **_kwargs) -> HostActionResult:
            steps.append(name)
            return outcomes.get(name, HostActionResult(True, {name: "ok"}))

        return run

    for name in (
        "quit_sign_in_apps",
        "quit_terminal_app",
        "execute_full_test_machine_reset",
        "relaunch_terminal_app",
    ):
        monkeypatch.setattr(ssh_mac_transport, name, step(name))
    host = SimpleNamespace(
        _run=None,
        _user="tester",
        upload_remote_text=None,
        home="/Users/tester",
        golden_baseline_path="/Users/Shared/golden",
        path_state=None,
    )
    return SshMacTransport.reset_installer_test_host(host), steps


def test_reset_quits_terminal_first_and_relaunches_it_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, steps = _reset(monkeypatch)

    assert result.ok
    assert steps == [
        "quit_sign_in_apps",
        "quit_terminal_app",
        "execute_full_test_machine_reset",
        "relaunch_terminal_app",
    ]
    assert result.evidence["relaunch_terminal_app"] == "ok"


def test_a_terminal_that_will_not_quit_stops_the_reset_before_the_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = HostActionResult(False, {"terminal_quit": {}}, TERMINAL_QUIT_NOT_PROVED)

    result, steps = _reset(monkeypatch, quit_terminal_app=refused)

    assert result.error_code == TERMINAL_QUIT_NOT_PROVED
    assert steps == ["quit_sign_in_apps", "quit_terminal_app"]


def test_a_failed_restore_keeps_its_error_and_skips_the_relaunch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = HostActionResult(False, {"paths": []}, "test_mac_reset_failed")

    result, steps = _reset(monkeypatch, execute_full_test_machine_reset=failed)

    assert result.error_code == "test_mac_reset_failed"
    assert "relaunch_terminal_app" not in steps
    assert result.evidence["quit_terminal_app"] == "ok"
