"""Native Windows routes every browser page through the identity launcher."""

from __future__ import annotations

import json
import shlex
import subprocess
from types import SimpleNamespace

import pytest

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
    return operator.with_operator_browser(
        {"actions": [GATE], "capture_checkpoints": []},
        conn=object(),
        project_id=1,
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


def test_a_missing_shim_refuses_by_name():
    script = yoke_python.yoke_python_command(["yoke", "browser", "authorize"])
    assert "(Get-Command yoke.cmd -ErrorAction SilentlyContinue).Source" in script
    assert yoke_python.SHIM_UNREADABLE + ": " in script
    assert "exit 70" in script
