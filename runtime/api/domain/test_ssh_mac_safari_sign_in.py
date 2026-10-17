"""Safari sign-ins survive macOS resets: quit first, then keep the live cookie store."""

from __future__ import annotations

import json
from pathlib import Path
import shlex
from types import SimpleNamespace

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    assignment,
    function_program,
    require_zsh,
    run_functions,
)
from yoke_harness.ssh_mac_preserved_state import (
    PRESERVED_HOME_ENTRIES,
    PRESERVED_MANIFEST_KEY,
    PRESERVED_MANIFEST_VALUE,
    SAFARI_COOKIE_HOME_ENTRY as COOKIES,
)
from yoke_harness.ssh_mac_sign_in_apps import (
    SIGN_IN_APP_PROBE_FAILED,
    SIGN_IN_APP_QUIT_NOT_PROVED,
    quit_sign_in_apps,
)

COOKIE_FILE = f"{COOKIES}/Cookies.binarycookies"
SAFARI_HISTORY = "Library/Containers/com.apple.Safari/Data/Library/Safari/History.db"


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _program(home: Path) -> tuple[str, ...]:
    require_zsh()
    return (function_program(), assignment("home", str(home)), "failure_detail=''")


def test_sign_in_then_reset_keeps_safaris_flushed_cookie_store(tmp_path):
    home, golden = tmp_path / "home", tmp_path / "golden"
    # Safari quit after the operator signed in, flushing the cookie to disk.
    _write(home, COOKIE_FILE, "signed in as the test account")
    _write(home, SAFARI_HISTORY, "live history")
    # An older golden captured Safari's store before the sign-in reached disk.
    _write(golden, COOKIE_FILE, "signed out")
    _write(golden, SAFARI_HISTORY, "golden history")
    error = tmp_path / "restore-errors"
    result = run_functions(
        (
            *_program(home),
            assignment("golden", str(golden)),
            assignment("restore_error_log", str(error)),
            assignment("restore_failure_report", str(error) + ".entries"),
            ': > "$restore_error_log"',
            ': > "$restore_failure_report"',
            "clear_home_levels",
            "restore_golden_levels",
            f"cd -- {shlex.quote(str(home))}",
            "list_capture_entries",
        ),
        shell_home=tmp_path / "shell",
    )
    assert result.returncode == 0, result.stderr
    assert (home / COOKIE_FILE).read_text() == "signed in as the test account"
    assert (home / SAFARI_HISTORY).read_text() == "golden history"
    captured = {
        entry.removeprefix("./") for entry in result.stdout.split("\0") if entry
    }
    assert not any(entry.startswith(COOKIES) for entry in captured)
    assert SAFARI_HISTORY in captured
    assert error.read_text() == ""


def _manifest_rejects(tmp_path: Path, declared: list[str], carried: bool) -> bool:
    home, golden = tmp_path / "home", tmp_path / "golden"
    home.mkdir()
    golden.mkdir()
    if carried:
        _write(golden, COOKIE_FILE, "captured cookies")
    line = f"{PRESERVED_MANIFEST_KEY} {json.dumps(declared, separators=(',', ':'))}"
    Path(str(golden) + ".manifest").write_text(line + "\n")
    result = run_functions(
        (
            *_program(home),
            assignment("golden", str(golden)),
            "manifest_suffix=.manifest",
            "validate_preserved_manifest || print -r -- REJECTED",
        ),
        shell_home=tmp_path / "shell",
    )
    return "REJECTED" in result.stdout


def test_a_golden_sealed_before_safari_was_kept_stays_resettable(tmp_path):
    earlier = [entry for entry in PRESERVED_HOME_ENTRIES if entry != COOKIES]
    # Its captured cookie store is inert: the restore never copies a kept entry.
    assert not _manifest_rejects(tmp_path, earlier, carried=True)


def test_a_golden_declaring_safari_must_not_carry_its_cookies(tmp_path):
    assert json.loads(PRESERVED_MANIFEST_VALUE)[-1] == COOKIES
    assert _manifest_rejects(tmp_path, json.loads(PRESERVED_MANIFEST_VALUE), True)


class SafariHost:
    def __init__(self, *, running: bool, exits: bool) -> None:
        self.running, self.exits = running, exits
        self.commands: list[str] = []

    def run(self, command: str, *, timeout: int = 60):
        self.commands.append(command)
        if command.startswith("/usr/bin/osascript"):
            self.running = not self.exits
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if "while" in command:
            return SimpleNamespace(returncode=1 if self.running else 0, stdout="")
        return SimpleNamespace(returncode=0 if self.running else 1, stdout="")


def test_running_safari_is_asked_to_quit_and_proved_gone():
    host = SafariHost(running=True, exits=True)
    result = quit_sign_in_apps(host.run, "tester")
    assert result.ok and result.evidence == {"sign_in_apps_quit": ["Safari"]}
    assert any('tell application "Safari" to quit' in c for c in host.commands)
    assert not any("kill" in c for c in host.commands)


def test_safari_not_running_is_left_alone():
    host = SafariHost(running=False, exits=True)
    result = quit_sign_in_apps(host.run, "tester")
    assert result.ok and result.evidence == {"sign_in_apps_quit": []}
    assert not any(c.startswith("/usr/bin/osascript") for c in host.commands)


def test_safari_that_will_not_quit_refuses_without_force():
    host = SafariHost(running=True, exits=False)
    result = quit_sign_in_apps(host.run, "tester")
    assert not result.ok and result.error_code == SIGN_IN_APP_QUIT_NOT_PROVED
    assert "Quit Safari on the test machine" in result.evidence["recovery"]
    assert not any("kill" in c for c in host.commands)


def test_a_failed_running_probe_is_not_read_as_safari_not_running():
    def run(command: str, *, timeout: int = 60):
        return SimpleNamespace(
            returncode=124, stdout="", stderr="host_control subprocess unavailable"
        )

    result = quit_sign_in_apps(run, "tester")
    assert not result.ok and result.error_code == SIGN_IN_APP_PROBE_FAILED
    assert result.evidence["probe"] == "running"
    assert result.evidence["exit_code"] == 124
    assert result.evidence["stderr"] == "host_control subprocess unavailable"
    assert "retry" in result.evidence["recovery"]


def test_a_failed_exit_probe_is_not_read_as_safari_gone():
    host = SafariHost(running=True, exits=True)

    def run(command: str, *, timeout: int = 60):
        if "while" in command:
            return SimpleNamespace(returncode=255, stdout="", stderr="ssh: closed")
        return host.run(command, timeout=timeout)

    result = quit_sign_in_apps(run, "tester")
    assert not result.ok and result.error_code == SIGN_IN_APP_PROBE_FAILED
    assert result.evidence["probe"] == "exited"


def test_capture_quits_safari_after_proving_probes_and_before_copying(monkeypatch):
    from yoke_harness import ssh_mac_golden_capture
    from yoke_harness.test_machine_types import HostActionResult

    order: list[str] = []
    monkeypatch.setattr(
        ssh_mac_golden_capture,
        "prove_probes_document",
        lambda *a: order.append("probes") or HostActionResult(True, {}),
    )
    monkeypatch.setattr(
        ssh_mac_golden_capture,
        "quit_sign_in_apps",
        lambda run, user: (
            order.append(f"quit:{user}")
            or HostActionResult(True, {"sign_in_apps_quit": ["Safari"]})
        ),
    )
    monkeypatch.setattr(
        ssh_mac_golden_capture,
        "execute_golden_capture",
        lambda **kw: order.append("copy") or HostActionResult(True, {}),
    )
    control = SimpleNamespace(
        home="/Users/tester",
        run_remote_command=None,
        upload_remote_text=None,
        path_state=None,
    )
    result = ssh_mac_golden_capture.capture_golden_baseline(
        control, destination="/Users/Shared/golden"
    )
    assert result.ok and result.evidence["sign_in_apps_quit"] == ["Safari"]
    assert order == ["probes", "quit:tester", "copy"]


def test_reset_quits_safari_before_the_clear_and_stops_if_it_will_not(monkeypatch):
    from yoke_harness import ssh_mac_transport
    from yoke_harness.test_machine_types import HostActionResult

    order: list[str] = []
    quit_result = HostActionResult(True, {"sign_in_apps_quit": ["Safari"]})
    monkeypatch.setattr(
        ssh_mac_transport,
        "quit_sign_in_apps",
        lambda run, user: order.append(f"quit:{user}") or quit_result,
    )
    monkeypatch.setattr(
        ssh_mac_transport,
        "execute_full_test_machine_reset",
        lambda **kw: order.append("reset") or HostActionResult(True, {"restored": 1}),
    )
    host = SimpleNamespace(
        _run=None,
        _user="tester",
        upload_remote_text=None,
        home="/Users/tester",
        golden_baseline_path="/Users/Shared/golden",
        path_state=None,
    )
    result = ssh_mac_transport.SshMacTransport.reset_installer_test_host(host)
    assert result.ok and result.evidence["sign_in_apps_quit"] == ["Safari"]
    assert order == ["quit:tester", "reset"]
    quit_result = HostActionResult(
        False, {"app": "Safari"}, SIGN_IN_APP_QUIT_NOT_PROVED
    )
    order.clear()
    result = ssh_mac_transport.SshMacTransport.reset_installer_test_host(host)
    assert result.error_code == SIGN_IN_APP_QUIT_NOT_PROVED and order == ["quit:tester"]
