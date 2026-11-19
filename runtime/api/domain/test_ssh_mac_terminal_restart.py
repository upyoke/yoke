"""A test-machine reset quits every leftover app and relaunches Terminal once restored."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from yoke_harness import ssh_mac_transport
from yoke_harness.ssh_mac_gui_app_sweep import GUI_APP_LIST_FAILED, LIST_COMMAND
from yoke_harness.ssh_mac_terminal_restart import (
    GUI_APP_PROBE_FAILED,
    GUI_APP_QUIT_NOT_PROVED,
    RELAUNCH_COMMAND,
    RESET_CONSOLE_USER_MISMATCH,
    TERMINAL_RELAUNCH_FAILED,
    quit_reset_apps,
    relaunch_terminal_app,
)
from yoke_harness.ssh_mac_transport import SshMacTransport
from yoke_contracts.test_machine_types import HostActionResult


def _done(returncode: int, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


# name, bundle ID, pid, LaunchServices type
_SESSION = [
    ("Dock", "com.apple.dock", 401, "UIElement"),
    ("Finder", "com.apple.finder", 402, "Foreground"),
    ("Terminal", "com.apple.Terminal", 501, "Foreground"),
    ("Claude", "com.anthropic.claudefordesktop", 502, "Foreground"),
    ("Cursor", "com.todesktop.230313mzl4w4u92", 503, "Foreground"),
    ("Codex", "com.openai.codex", 504, "Foreground"),
    ("Google Chrome", "com.google.Chrome", 505, "Foreground"),
    ("Docker Desktop", "com.docker.docker", 506, "Foreground"),
    ("System Events", "com.apple.systemevents", 507, "BackgroundOnly"),
]


def _listing(apps) -> str:
    return "".join(
        f' {n}) "{name}" ASN:0x0-0x{n}: \n    bundleID="{bundle}"\n'
        f'    pid = {pid} type="{kind}" flavor=3 Arch=ARM64 \n'
        for n, (name, bundle, pid, kind) in enumerate(apps, 1)
    )


class SessionHost:
    """A GUI session whose apps quit when asked, unless a sheet holds one."""

    def __init__(
        self,
        *,
        apps=_SESSION,
        held: frozenset[str] = frozenset(),
        unkillable: frozenset[str] = frozenset(),
        console_user: str = "tester",
        list_rc: int = 0,
        pgrep_rc: int | None = None,
    ) -> None:
        self.pids = {bundle: pid for _, bundle, pid, _ in apps}
        self.alive = set(self.pids.values())
        self.apps, self.held, self.unkillable = apps, held, unkillable
        self.console_user, self.list_rc, self.pgrep_rc = console_user, list_rc, pgrep_rc
        self.commands: list[str] = []

    def _probe(self, command: str) -> SimpleNamespace:
        if self.pgrep_rc is not None:
            return _done(self.pgrep_rc, stderr="ssh: connection reset")
        pid = re.search(r"grep -x (\d+)", command)
        if pid is None:
            alive = self.pids["com.apple.systemevents"] in self.alive
        else:
            alive = int(pid[1]) in self.alive
        return _done(0 if alive else 1)

    def __call__(
        self, command: str, *, timeout: int = 60, input_text: str | None = None
    ) -> SimpleNamespace:
        command = input_text if input_text is not None else command
        self.commands.append(command)
        if command == "/usr/bin/stat -f%Su /dev/console":
            return _done(0, f"{self.console_user}\n")
        if command == LIST_COMMAND:
            out = _listing(self.apps) if self.list_rc == 0 else ""
            return _done(self.list_rc, out, "" if self.list_rc == 0 else "lsappinfo: denied")
        if "whose visible is true" in command:
            return _done(0, "241\n")
        quit = re.search(r'tell application (?:id )?"([^"]+)" to quit', command)
        if quit:
            bundle = "com.apple.systemevents" if quit[1] == "System Events" else quit[1]
            if bundle not in self.held:
                self.alive.discard(self.pids[bundle])
            return _done(0)
        if "process_tree()" in command:
            for bundle, pid in self.pids.items():
                named = bundle == "com.apple.systemevents" and "System Events" in command
                if (named or f"grep -x {pid}" in command) and bundle not in self.unkillable:
                    self.alive.discard(pid)
            return _done(0)
        if "while" in command:
            # The wait exits 0 once the app is gone and 1 while it still runs.
            probe = self._probe(command).returncode
            return _done(3 if probe > 1 else 1 - probe)
        return self._probe(command)


def _quit(result, name: str) -> dict:
    return next(e for e in result.evidence["gui_apps_quit"] if e["app"] == name)


def test_reset_quits_every_leftover_app_and_keeps_the_ones_it_needs() -> None:
    host = SessionHost(held=frozenset({"com.openai.codex"}))

    result = quit_reset_apps(host, "tester")

    assert result.ok, result.evidence
    quit = [entry["app"] for entry in result.evidence["gui_apps_quit"]]
    assert quit == ["Terminal", "Claude", "Cursor", "Codex"]
    assert _quit(result, "Terminal") == {
        "app": "Terminal",
        "bundle_id": "com.apple.Terminal",
        "pid": 501,
        "windows_before_quit": 241,
        "quit": "graceful",
    }
    assert _quit(result, "Claude")["quit"] == "graceful"
    assert _quit(result, "Codex")["quit"] == "forced"
    assert result.evidence["gui_apps_kept"] == ["Finder", "Google Chrome", "Docker Desktop"]
    assert result.evidence["system_events_quit"]["quit"] == "graceful"
    assert host.alive == {401, 402, 505, 506}
    for kept in ("com.apple.finder", "com.google.Chrome", "com.docker.docker", "Dock"):
        assert not any(kept in c and "quit" in c for c in host.commands)
    kills = [c for c in host.commands if "process_tree()" in c]
    assert len(kills) == 1 and "grep -x 504" in kills[0]


def test_every_process_command_is_scoped_to_the_test_user() -> None:
    host = SessionHost(held=frozenset({"com.openai.codex"}))

    quit_reset_apps(host, "tester")

    process_commands = [c for c in host.commands if "pgrep" in c]
    assert process_commands
    for command in process_commands:
        assert all(
            "-u tester" in call for call in re.findall(r"pgrep[^;|)]*", command)
            if "pgrep -P" not in call
        ), command
    kill = next(c for c in host.commands if "process_tree()" in c)
    assert "/usr/bin/pgrep -u tester ." in kill
    assert "/bin/kill -KILL" in kill


def test_an_app_surviving_the_kill_refuses_with_a_console_recovery() -> None:
    host = SessionHost(
        held=frozenset({"com.anthropic.claudefordesktop"}),
        unkillable=frozenset({"com.anthropic.claudefordesktop"}),
    )

    result = quit_reset_apps(host, "tester")

    assert not result.ok
    assert result.error_code == GUI_APP_QUIT_NOT_PROVED
    assert "Quit Claude at the host console" in result.evidence["recovery"]
    assert _quit(result, "Claude")["quit"] == "forced"
    assert not any("Cursor" in e["app"] for e in result.evidence["gui_apps_quit"])


def test_an_unreadable_process_table_is_not_taken_as_stopped() -> None:
    result = quit_reset_apps(SessionHost(pgrep_rc=255), "tester")

    assert not result.ok
    assert result.error_code == GUI_APP_PROBE_FAILED
    assert _quit(result, "Terminal")["exit_code"] == 255


@pytest.mark.parametrize("apps,list_rc", [(_SESSION, 1), (_SESSION[1:], 0)])
def test_an_unlisted_session_refuses_instead_of_skipping_the_sweep(apps, list_rc):
    host = SessionHost(apps=apps, list_rc=list_rc)

    result = quit_reset_apps(host, "tester")

    assert not result.ok
    assert result.error_code == GUI_APP_LIST_FAILED
    assert "Check that SSH" in result.evidence["recovery"]
    assert not any("to quit" in c for c in host.commands)


def test_a_different_console_user_refuses_before_any_quit() -> None:
    host = SessionHost(console_user="someone")

    result = quit_reset_apps(host, "tester")

    assert not result.ok
    assert result.error_code == RESET_CONSOLE_USER_MISMATCH
    assert result.evidence["console_user"] == "someone"
    assert host.commands == ["/usr/bin/stat -f%Su /dev/console"]


@pytest.mark.parametrize(
    "held,unkillable,ok,kind",
    [
        (frozenset(), frozenset(), True, "graceful"),
        ({"com.apple.systemevents"}, frozenset(), True, "forced"),
        ({"com.apple.systemevents"}, {"com.apple.systemevents"}, False, "forced"),
    ],
)
def test_reset_stops_system_events_after_the_apps(held, unkillable, ok, kind):
    host = SessionHost(held=frozenset(held), unkillable=frozenset(unkillable))

    result = quit_reset_apps(host, "tester")

    assert result.ok is ok
    assert result.evidence["system_events_quit"]["quit"] == kind
    events = next(i for i, c in enumerate(host.commands) if "System Events" in c)
    assert all(
        "System Events" in c or "to quit" not in c for c in host.commands[events:]
    )
    if not ok:
        assert result.error_code == "test_machine_system_events_quit_not_proved"
        assert "Activity Monitor" in result.evidence["recovery"]


def test_relaunch_skips_saved_windows_and_waits_for_the_first_window() -> None:
    commands: list[str] = []

    def run(
        command: str, *, timeout: int = 60, input_text: str | None = None
    ) -> SimpleNamespace:
        commands.append(command)
        if command == RELAUNCH_COMMAND:
            return _done(0)
        assert command == "/bin/sh -s"
        assert input_text is not None
        assert "whose visible is true" in input_text
        assert "| /usr/bin/osascript" in input_text
        return _done(0, "1\n")

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
    def run(
        command: str, *, timeout: int = 60, input_text: str | None = None
    ) -> SimpleNamespace:
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
        "quit_reset_apps",
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
        "quit_reset_apps",
        "execute_full_test_machine_reset",
        "relaunch_terminal_app",
    ]
    assert result.evidence["relaunch_terminal_app"] == "ok"


def test_an_app_that_will_not_quit_stops_the_reset_before_the_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = HostActionResult(False, {"gui_apps_quit": []}, GUI_APP_QUIT_NOT_PROVED)

    result, steps = _reset(monkeypatch, quit_reset_apps=refused)

    assert result.error_code == GUI_APP_QUIT_NOT_PROVED
    assert steps == ["quit_sign_in_apps", "quit_reset_apps"]


def test_a_failed_restore_keeps_its_error_and_skips_the_relaunch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = HostActionResult(False, {"paths": []}, "test_mac_reset_failed")

    result, steps = _reset(monkeypatch, execute_full_test_machine_reset=failed)

    assert result.error_code == "test_mac_reset_failed"
    assert "relaunch_terminal_app" not in steps
    assert result.evidence["quit_reset_apps"] == "ok"
