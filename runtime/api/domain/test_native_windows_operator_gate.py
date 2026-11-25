"""Native Windows routes every browser page through the identity launcher."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_cli.config import cli_release_runtime
from yoke_core.domain import machine_qa_operator_browser as operator
from yoke_core.domain import native_windows_operator_gate as gate
from yoke_harness import identity_browser_approval as driver
from yoke_core.domain import ssh_native_windows_host_control as host_control
from yoke_harness.native_windows import yoke_python

GATE = {
    "step": "approve",
    "operator_gate": "machine_browser_approval",
    "keys": [],
    "gate_timeout_seconds": 60.0,
}
DECLARED = {"identities": {"operator": {"sites": []}}, "default_identity": "operator"}
ORIGIN = "https://app.example"
SCREEN = f"Open: {ORIGIN}/connect?user_code=K7F2\nMatch code: K7F2\n"
YOKE_BIN = r"C:\Users\tester\.local\bin\yoke.cmd"
REAUTHORIZE = (
    "yoke browser authorize --project acme --identity operator "
    "--test-machine windows-native-lab"
)


def _windows_config(monkeypatch):
    monkeypatch.setattr(operator, "_browser_settings", lambda conn, pid: DECLARED)
    config = {"actions": [GATE], "capture_checkpoints": []}
    return operator.with_operator_browser(
        config,
        identity=operator.operator_identity(object(), 1, [{"method_config": config}]),
        project="acme",
        test_machine="windows-native-lab",
        os_name="windows",
    )


def test_native_windows_names_the_operator_identity(monkeypatch):
    config = _windows_config(monkeypatch)
    assert config[operator.OPERATOR_BROWSER]["identity"] == "operator"
    assert config[operator.OPERATOR_BROWSER]["os"] == "windows"
    assert operator.reauthorize_command(config) == REAUTHORIZE


def test_the_powershell_export_sets_a_backslash_free_browser(monkeypatch):
    prefix = operator.browser_export(_windows_config(monkeypatch))
    assert "export " not in prefix and "env -u" not in prefix
    assert prefix.startswith(
        "$env:Path=(Split-Path -Parent {yoke_bin})+';'+$env:Path; "
    )
    assert "Remove-Item Env:YOKE_MACHINE_HOME -ErrorAction SilentlyContinue; " in prefix
    value = prefix.split("$env:BROWSER='", 1)[1].split("'; ", 1)[0]
    assert "\\" not in value
    # Yoke's BROWSER opener splits the value with POSIX shlex.
    assert shlex.split(value) == [
        "yoke.cmd", "browser", "open", "--project", "acme",
        "--identity", "operator", "%s",
    ]


class _Terminal:
    token = "YokeQa-test"

    def __init__(self):
        self.sent = []
        self.captured = 0

    def transcript(self):
        return SCREEN

    def send(self, key, *, submit=True):
        self.sent.append(key)
        return True

    def capture_window(self):
        self.captured += 1
        return {"sha256": "desktop"}


class _Control:
    path_state = SimpleNamespace(yoke_bin=YOKE_BIN)
    secret_values = ()

    def __init__(self, tab_urls):
        self.scripts = []
        self.tab_urls = tab_urls

    def _run(self, script, *, timeout=60):
        self.scripts.append(script)
        receipt = {"ok": True, "urls": self.tab_urls, "identity_browsers": 1}
        return subprocess.CompletedProcess([], 0, json.dumps(receipt), "")


@pytest.fixture
def windows_port(monkeypatch):
    monkeypatch.setattr(driver.identity_browser_devtools, "TAB_WAIT_SECONDS", 0)
    monkeypatch.setattr(
        gate,
        "get_identity_browser_approval",
        lambda: SimpleNamespace(approve_machine_in_identity_browser=driver.approve_machine_in_identity_browser),
    )
    monkeypatch.setattr(
        gate,
        "get_ssh_windows_host_operations",
        lambda: SimpleNamespace(yoke_python_command=yoke_python.yoke_python_command),
    )


def test_the_driver_runs_on_the_host_through_the_installed_python(windows_port):
    control = _Control([f"{ORIGIN}/elsewhere"])
    rows = []
    gate.run_operator_gate(
        control, _Terminal(), GATE, rows, (ORIGIN,), None, REAUTHORIZE
    )
    script = control.scripts[0]
    assert script.startswith(f"$shimPath='{YOKE_BIN}'")
    assert "[IO.File]::ReadAllText($shimPath)" in script
    assert "$info.FileName=$Matches[1]" in script
    assert f"'browser devtools tabs {ORIGIN}'" in script
    assert "cmd.exe" not in script


def test_an_expired_login_refuses_naming_the_windows_authorize_command(windows_port):
    control = _Control([f"{ORIGIN}/auth/sign-in?return_to=/connect"])
    rows = []
    failed = gate.run_operator_gate(
        control, _Terminal(), GATE, rows, (ORIGIN,), None, REAUTHORIZE
    )
    assert failed is not None and not failed.ok
    approval = failed.evidence["browser_approval"]
    assert rows[-1]["browser_automation_error_code"] == "machine_browser_sign_in_required"
    assert f"`{REAUTHORIZE}`" in approval["recovery"]


def test_the_windows_recipe_runs_the_gate_instead_of_refusing(monkeypatch):
    from yoke_core.domain import native_windows_terminal_recipe as recipe

    calls = []
    monkeypatch.setattr(
        recipe,
        "run_operator_gate",
        lambda control, terminal, action, rows, urls, progress, reauthorize: (
            calls.append((urls, reauthorize))
            or rows.append({"key": "approve", "reached": True, "transcript": SCREEN})
        ),
    )
    terminal = SimpleNamespace(
        launch=lambda entry, size: True,
        close=lambda: True,
        transcript=lambda: SCREEN + "__YOKE_EXIT_0\n",
    )
    config = {
        "max_wall_seconds": 30,
        "actions": [GATE],
        "capture_checkpoints": [],
        "expected_text": [],
        "post_checks": [],
        "operator_browser": {
            "project": "acme",
            "identity": "operator",
            "test_machine": "windows-native-lab",
            "os": "windows",
        },
    }
    result = recipe._interactive(
        object(), terminal, "yoke setup", "approve", config, None, (), (120, 40), (ORIGIN,)
    )
    assert calls == [((ORIGIN,), REAUTHORIZE)]
    assert result.ok


@pytest.mark.parametrize(
    ("argv", "routed"),
    [
        (["yoke", "browser", "open", "--project", "acme", "https://a"], True),
        (["yoke", "qa", "browser", "setup", "--project", "acme"], True),
        ([YOKE_BIN, "qa", "browser", "step"], True),
        (["yoke", "browser", "authorize"], False),
        (["notepad.exe", "browser", "open"], False),
    ],
)
def test_page_commands_start_in_the_interactive_desktop(monkeypatch, argv, routed):
    ran = []
    monkeypatch.setattr(
        host_control,
        "get_ssh_windows_host_operations",
        lambda: SimpleNamespace(
            opens_identity_page=yoke_python.opens_identity_page,
            yoke_python_command=yoke_python.yoke_python_command,
            desktop_script=lambda control, script, timeout: ran.append(script)
            or subprocess.CompletedProcess([], 0, "", ""),
        ),
    )
    monkeypatch.setattr(
        host_control.SshNativeWindowsHostOperations,
        "run_command",
        lambda self, argv, **kw: subprocess.CompletedProcess([], 0, "ssh", ""),
    )
    control = object.__new__(host_control.SshNativeWindowsHostControl)
    control.path_state = SimpleNamespace(yoke_bin=YOKE_BIN)
    result = control.run_command(argv, timeout=30)
    if routed:
        assert result.desktop_session == "interactive"
        assert ran[0].startswith(f"$shimPath='{YOKE_BIN}'")
        assert "'" + " ".join(argv[1:3]) in ran[0]
    else:
        assert ran == [] and result.stdout == "ssh"


def test_the_shim_reader_recognizes_the_installer_and_earlier_formats(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_release_runtime, "WINDOWS", True)
    root, python = tmp_path / "Yoke data", tmp_path / "Python install/python.exe"
    shim = tmp_path / "yoke.cmd"
    current = cli_release_runtime._shims(root, python, tmp_path)[shim]
    script = yoke_python.yoke_python_command([YOKE_BIN, "qa", "browser", "setup"])
    check = re.search(r"if\(\$shim -notmatch '([^']+)'\)", script)
    assert check
    pattern = re.compile(check.group(1))
    legacy = f'@"{python}" "{root / "launcher"}" %*'
    for contents in (current, legacy, legacy + " & exit /b", legacy + " & call exit /b %%ERRORLEVEL%%"):
        match = pattern.match(contents)
        assert match and match.groups() == (str(python), str(root / "launcher"))
    assert pattern.match('@echo "foreign shim"') is None


@pytest.mark.windows
@pytest.mark.windows_only(reason="PowerShell runs the installed Python launcher")
def test_the_windows_browser_runner_executes_through_the_generated_shim(tmp_path):
    root = tmp_path / "Yoke data"
    root.mkdir()
    (root / "launcher").write_text(
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\nsys.exit(7)\n",
        encoding="utf-8",
    )
    shim = tmp_path / "yoke.cmd"
    shim.write_bytes(cli_release_runtime._shims(root, Path(sys.executable), tmp_path)[shim].encode())
    arguments = ["qa", "browser", "step", "--step-json", '{"text":"spaces & 100%"}']
    # First-use module preparation may emit progress on PowerShell's stderr.
    script = "$ProgressPreference='SilentlyContinue'\n" + yoke_python.yoke_python_command(
        [str(shim), *arguments]
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=30,
    )
    assert result.stderr == ""
    assert (result.returncode, json.loads(result.stdout)) == (7, arguments)


def test_a_missing_shim_refuses_by_name():
    from yoke_contracts.windows_powershell import SHIM_UNREADABLE

    script = yoke_python.yoke_python_command(["yoke", "browser", "authorize"])
    assert "(Get-Command yoke.cmd -ErrorAction SilentlyContinue).Source" in script
    assert SHIM_UNREADABLE + ": " in script
    assert "exit 70" in script


def test_the_windows_recipe_stages_files_before_opening_the_console(monkeypatch):
    from yoke_contracts.test_machine_types import HostActionResult
    from yoke_core.domain import native_windows_terminal_recipe as recipe

    uploads, removed = [], []
    monkeypatch.setattr(
        recipe,
        "get_ssh_windows_host_operations",
        lambda: SimpleNamespace(WindowsTerminal=lambda control: "terminal"),
    )
    monkeypatch.setattr(
        recipe, "_interactive", lambda *args: HostActionResult(True, {"steps": []})
    )
    source = __file__
    control = SimpleNamespace(
        secret_values=(),
        _pending_terminal_size=(120, 40),
        _upload_bytes=lambda path, content: uploads.append(path) or True,
        check_connection=lambda: HostActionResult(True, {"host": "lab"}),
        run_command=lambda argv: removed.append(argv[-1])
        or subprocess.CompletedProcess(argv, 0, "", ""),
    )
    remote = r"C:\Users\qa\AppData\Local\YokeQa\case.txt"
    result = recipe.execute_recipe(
        control,
        entry_surface="yoke setup",
        required_completion="done",
        config={
            "execution_mode": "terminal",
            "stage_files": [{"remote_path": remote, "source_path": source}],
        },
    )
    assert result.ok
    assert uploads == [remote] and removed == [remote]
    assert result.evidence["staged_files"][0]["remote_path"] == remote


def test_a_stalled_console_fails_with_its_screen_and_the_missing_text():
    import time

    from yoke_core.domain import native_windows_terminal_recipe as recipe
    from yoke_harness.native_windows.terminal import WindowsTerminal

    screen = "Installing Yoke...\nwindows_untrusted_mount_point\n"
    terminal = SimpleNamespace(
        launch=lambda entry, size: True,
        close=lambda: True,
        transcript=lambda: screen,
        capture_window=lambda: {"sha256": "console"},
    )
    terminal.wait_for = lambda expected, deadline, progress=None: (
        WindowsTerminal.wait_for(terminal, expected, deadline, progress)
    )
    action = {"step": "browser-approval", "ready_text": ["Open:", "Match code:"],
              "ready_timeout_seconds": 0, "keys": []}
    config = {"max_wall_seconds": 600, "actions": [action], "step_delay": 0,
              "capture_checkpoints": [], "expected_text": [], "post_checks": []}
    started = time.monotonic()
    result = recipe._interactive(
        object(), terminal, "irm | iex", "machine-approved", config, None, (), (120, 40), ()
    )
    # The step's own bound ends the wait, not the 600-second case bound.
    assert time.monotonic() - started < 5
    assert not result.ok
    assert result.error_code == "windows_terminal_readiness_timeout"
    stalled = result.evidence["steps"][-1]
    assert stalled["key"] == "browser-approval" and stalled["transcript"] == screen
    assert stalled["missing"] == ["Open:", "Match code:"]
    assert stalled["sha256"] == "console"
