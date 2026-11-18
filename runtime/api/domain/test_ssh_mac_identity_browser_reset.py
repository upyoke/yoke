"""macOS resets close the identity browsers first and keep only the identity store."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from runtime.api.domain.ssh_mac_full_reset_test_support import (
    assignment,
    function_program,
    require_zsh,
    run_functions,
)
from yoke_contracts.ssh_mac_preserved_state import (
    PRESERVED_HOME_ENTRIES,
    PRESERVED_MANIFEST_KEY,
    PRESERVED_MANIFEST_VALUE,
    RETIRED_PRESERVED_HOME_ENTRIES,
)
from yoke_harness import ssh_mac_sign_in_apps as sign_in_apps
from yoke_harness.ssh_mac_sign_in_apps import (
    SIGN_IN_APP_PROBE_FAILED,
    SIGN_IN_APP_QUIT_NOT_PROVED,
    quit_sign_in_apps,
)

SAFARI_COOKIES = RETIRED_PRESERVED_HOME_ENTRIES[0]


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _manifest_rejects(tmp_path: Path, declared: list[str], carried: bool) -> bool:
    require_zsh()
    home, golden = tmp_path / "home", tmp_path / "golden"
    home.mkdir()
    golden.mkdir()
    if carried:
        _write(golden, declared[-1] + "/data", "captured")
    line = f"{PRESERVED_MANIFEST_KEY} {json.dumps(declared, separators=(',', ':'))}"
    Path(str(golden) + ".manifest").write_text(line + "\n")
    result = run_functions(
        (
            function_program(),
            assignment("home", str(home)),
            "failure_detail=''",
            assignment("golden", str(golden)),
            "manifest_suffix=.manifest",
            "validate_preserved_manifest || print -r -- REJECTED",
        ),
        shell_home=tmp_path / "shell",
    )
    return "REJECTED" in result.stdout


def test_safari_is_no_longer_a_kept_login_store():
    assert SAFARI_COOKIES not in PRESERVED_HOME_ENTRIES
    assert SAFARI_COOKIES not in json.loads(PRESERVED_MANIFEST_VALUE)


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
def test_a_golden_sealed_while_safari_was_kept_stays_resettable(tmp_path):
    declared = [*PRESERVED_HOME_ENTRIES, SAFARI_COOKIES]
    assert not _manifest_rejects(tmp_path, declared, carried=False)


@pytest.mark.macos_only(reason="executes a macOS reset or capture program in /bin/zsh")
def test_a_golden_naming_an_unknown_entry_is_refused(tmp_path):
    declared = [*PRESERVED_HOME_ENTRIES, "Library/Unknown/Store"]
    assert _manifest_rejects(tmp_path, declared, carried=False)


def _host_result(code, stderr=""):
    return subprocess.CompletedProcess([], code, "", stderr)


def test_running_identity_browsers_are_asked_to_quit_with_guaranteed_primitives():
    commands = []

    def run(command, *, timeout=60):
        commands.append(command)
        return _host_result(0)

    result = quit_sign_in_apps(run, "tester")
    assert result.ok and result.evidence == {"sign_in_apps_quit": ["identity browser"]}
    script = commands[0]
    assert "python" not in script.casefold()
    assert "/bin/ps -U tester" in script and "/bin/kill -TERM" in script
    assert "-KILL" not in script and "-9" not in script


def test_the_probe_never_matches_its_own_command_line(tmp_path):
    script = sign_in_apps._close_script("tester")
    assert "--user-data-dir=" not in script
    assert '"--user-data" "-dir="' in script


def test_no_identity_browser_running_is_left_alone():
    result = quit_sign_in_apps(lambda *a, **k: _host_result(10), "tester")
    assert result.ok and result.evidence == {"sign_in_apps_quit": []}


def test_a_browser_that_will_not_close_refuses_without_force():
    result = quit_sign_in_apps(lambda *a, **k: _host_result(11), "tester")
    assert not result.ok and result.error_code == SIGN_IN_APP_QUIT_NOT_PROVED
    assert "not force-quit" in result.evidence["recovery"]


def test_a_failed_probe_is_not_read_as_closed():
    result = quit_sign_in_apps(lambda *a, **k: _host_result(255, "ssh: closed"), "tester")
    assert not result.ok and result.error_code == SIGN_IN_APP_PROBE_FAILED
    assert result.evidence["exit_code"] == 255
    assert result.evidence["stderr"] == "ssh: closed"


@pytest.mark.usefixtures("recorded_harness_clis")
def test_capture_closes_identity_browsers_after_proving_probes_and_before_copying(monkeypatch):
    from yoke_harness import ssh_mac_golden_capture
    from yoke_contracts.test_machine_types import HostActionResult

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
            or HostActionResult(True, {"sign_in_apps_quit": ["identity browser"]})
        ),
    )
    monkeypatch.setattr(
        ssh_mac_golden_capture,
        "execute_golden_capture",
        lambda **kw: order.append("copy") or HostActionResult(True, {}),
    )
    control = SimpleNamespace(
        home="/Users/tester",
        check_terminal_bridge=lambda: (
            order.append("bridge") or HostActionResult(True, {})
        ),
        run_remote_command=None,
        upload_remote_text=None,
        path_state=None,
    )
    result = ssh_mac_golden_capture.capture_golden_baseline(
        control, destination="/Users/Shared/golden"
    )
    assert result.ok and result.evidence["sign_in_apps_quit"] == ["identity browser"]
    assert result.evidence["harness_cli_versions"]["codex"] == "0.163.0"
    assert order == ["bridge", "probes", "quit:tester", "copy"]


def test_reset_closes_identity_browsers_before_the_clear_and_stops_if_they_will_not(monkeypatch):
    from yoke_harness import ssh_mac_transport
    from yoke_contracts.test_machine_types import HostActionResult

    order: list[str] = []
    quit_result = HostActionResult(True, {"sign_in_apps_quit": ["identity browser"]})
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
    for terminal_step in ("quit_reset_apps", "relaunch_terminal_app"):
        monkeypatch.setattr(
            ssh_mac_transport,
            terminal_step,
            lambda *_a, **_k: HostActionResult(True, {}),
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
    assert result.ok and result.evidence["sign_in_apps_quit"] == ["identity browser"]
    assert order == ["quit:tester", "reset"]
    quit_result = HostActionResult(
        False, {"app": "identity browser"}, SIGN_IN_APP_QUIT_NOT_PROVED
    )
    order.clear()
    result = ssh_mac_transport.SshMacTransport.reset_installer_test_host(host)
    assert result.error_code == SIGN_IN_APP_QUIT_NOT_PROVED and order == ["quit:tester"]
