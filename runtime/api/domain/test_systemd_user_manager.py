"""A missing systemd user manager refuses by name, with the host's own recovery."""

import json
import pathlib
import shlex
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_qa_failures import SSH_UNAVAILABLE
from yoke_contracts.systemd_user_manager import (
    USER_MANAGER_UNAVAILABLE,
    user_manager_unavailable,
)
from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness import ssh_linux_baseline
from yoke_harness.ssh_linux_host_operations import SshLinuxHostOperations
from yoke_harness.ssh_linux_user_manager import (
    RESET_USER_MANAGER_PROGRAM,
    check_linux_user_manager,
)
from yoke_harness.ssh_windows_host_operations import SshWindowsHostOperations
from yoke_harness.test_machine_operations import _verify

BUS_ERROR = "Failed to connect to bus: No medium found\n"


@pytest.mark.parametrize("distro,named", [("Lab-Distro", "Lab-Distro"), (None, "<distro>")])
def test_wsl_recovery_terminates_the_named_distro_and_never_lingers(distro, named):
    refusal = user_manager_unavailable(BUS_ERROR, wsl=True, distro=distro)
    assert refusal["user_manager_stderr"] == BUS_ERROR.strip()
    assert f"From Windows run `wsl.exe --terminate {named}`, then retry" in refusal["recovery"]
    assert "Never enable linger." in refusal["recovery"]
    assert "PAM" not in refusal["recovery"]


def test_linux_recovery_names_a_pam_login_and_the_callers_retry():
    refusal = user_manager_unavailable(
        BUS_ERROR, wsl=False, distro="ignored", retry="retry `yoke relay install`"
    )
    assert refusal == {
        "user_manager_stderr": BUS_ERROR.strip(),
        "recovery": "Log in through a PAM session with a systemd user manager, "
        "then retry `yoke relay install`.",
    }


def fake_host(monkeypatch, *, returncode, distro=None):
    commands = []

    def run(argv, **kwargs):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, returncode, "", BUS_ERROR)

    real_read_text = pathlib.Path.read_text

    def read_text(path, *args, **kwargs):
        if str(path) == "/proc/sys/kernel/osrelease":
            return "6.6.87.2-generic\n"
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    if distro:
        monkeypatch.setenv("WSL_DISTRO_NAME", distro)
    else:
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    return commands


def run_reset_check(monkeypatch, **host):
    commands = fake_host(monkeypatch, **host)

    def refuse(reason, entry=None, recovery=None, **details):
        raise RuntimeError(reason, {"recovery": recovery, **details})

    exec(RESET_USER_MANAGER_PROGRAM, {"refuse": refuse})
    return commands


@pytest.mark.parametrize("distro", ["Lab-Distro", None])
def test_reset_refuses_a_missing_user_manager_with_real_stderr(monkeypatch, distro):
    with pytest.raises(RuntimeError) as refused:
        run_reset_check(monkeypatch, returncode=1, distro=distro)
    reason, details = refused.value.args
    assert reason == USER_MANAGER_UNAVAILABLE
    assert details == user_manager_unavailable(BUS_ERROR, wsl=bool(distro), distro=distro)


def test_reset_proceeds_when_the_user_manager_answers(monkeypatch):
    commands = run_reset_check(monkeypatch, returncode=0)
    assert commands == [["systemctl", "--user", "show-environment"]]


def test_reset_checks_the_user_manager_before_any_stop_stash_or_removal(monkeypatch):
    captured = []

    def run_golden_command(control, command, **kwargs):
        captured.append(command)
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr=""), []

    monkeypatch.setattr(
        ssh_linux_baseline, "archive_admission", lambda *a: HostActionResult(True, {})
    )
    monkeypatch.setattr(ssh_linux_baseline, "run_golden_command", run_golden_command)
    control = SimpleNamespace(home="/home/tester", secret_values=())
    assert ssh_linux_baseline.archive_operation(control, "reset", "/srv/golden").ok
    program = shlex.split(captured[0])[2]
    compile(program, "<remote-linux-home-restore>", "exec")
    check = program.index("    missing = user_manager_missing()")
    for later in (
        "stash_live_home_entries()\n",
        "stop_desktop()\n",
        '["systemctl", "--user", "stop", unit]',
        '["docker", "rm", "--force"]',
        "entry.unlink()",
    ):
        assert check < program.index(later), later
    assert check > program.index('refuse("golden_baseline_identity_mismatch")')


def linux_control(manager, *, os_name="linux"):
    adapter = SshWindowsHostOperations if os_name == "wsl" else SshLinuxHostOperations
    control = object.__new__(adapter)
    control._host, control._user = "host.invalid", "tester"
    control.os = os_name
    control.secret_values = ()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "SC_PHYS_PAGES" in command:
            return SimpleNamespace(returncode=0, stdout=str(8 * 1024**3), stderr="")
        if "show-environment" in command:
            return SimpleNamespace(returncode=0, stdout=json.dumps(manager), stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    control._run = run
    return control, calls


def test_verify_fails_with_the_reset_code_stderr_and_recovery():
    refusal = user_manager_unavailable(BUS_ERROR, wsl=True, distro="Lab-Distro")
    control, calls = linux_control(refusal)
    result = control.check_connection()
    assert not result.ok and result.error_code == USER_MANAGER_UNAVAILABLE
    assert result.evidence["user_manager_stderr"] == refusal["user_manager_stderr"]
    assert result.evidence["recovery"] == refusal["recovery"]
    assert result.evidence["total_memory_bytes"] == 8 * 1024**3
    assert any("show-environment" in call for call in calls)


def test_wsl_verify_refuses_before_terminal_bridge_or_baseline_reset():
    refusal = user_manager_unavailable(BUS_ERROR, wsl=True, distro="Lab-Distro")
    control, calls = linux_control(refusal, os_name="wsl")
    control.check_terminal_bridge = lambda: pytest.fail("verify touched the desktop")
    control.reach_baseline = lambda _: pytest.fail("verify reset a baseline")
    contract = SimpleNamespace(
        checks=["connection", "terminal_bridge"], baselines=["fresh-host", "shell-preconfigured"]
    )

    rows, error = _verify(contract, control, None)

    assert error == USER_MANAGER_UNAVAILABLE
    assert [row["name"] for row in rows] == ["connection"]
    assert not rows[0]["ok"] and rows[0]["os"] == "wsl"
    assert rows[0]["user_manager_stderr"] == refusal["user_manager_stderr"]
    assert rows[0]["recovery"] == refusal["recovery"]
    assert calls[0] == "/usr/bin/true"
    assert len(calls) == 2 and "show-environment" in calls[1]


@pytest.mark.parametrize("os_name", ["linux", "wsl"])
def test_reset_refuses_before_identity_retirement_or_archive_admission(monkeypatch, os_name):
    refusal = user_manager_unavailable(BUS_ERROR, wsl=os_name == "wsl", distro="Lab-Distro")
    control, calls = linux_control(refusal, os_name=os_name)
    control.golden_baseline_path = "/srv/golden"
    monkeypatch.setattr(
        "yoke_harness.ssh_linux_host_operations.retire_reset_identity",
        lambda _: pytest.fail("reset attempted to retire the lab identity"),
    )
    monkeypatch.setattr(
        ssh_linux_baseline, "archive_admission", lambda *_: pytest.fail("reset entered archive admission")
    )

    result = control.reset_installer_test_host()

    assert not result.ok and result.error_code == USER_MANAGER_UNAVAILABLE
    assert result.evidence["user_manager_stderr"] == refusal["user_manager_stderr"]
    assert result.evidence["recovery"] == refusal["recovery"]
    assert len(calls) == 1 and "show-environment" in calls[0]


def test_verify_keeps_its_connection_row_when_the_user_manager_answers():
    control, _ = linux_control(None)
    result = control.check_connection()
    assert result.ok and result.error_code is None
    assert result.evidence["systemd_user_manager"] == "available"
    assert result.evidence["runner_materialized"] is True


def test_verify_probe_runs_the_same_check_on_the_host(monkeypatch):
    fake_host(monkeypatch, returncode=1, distro="Lab-Distro")

    def run(command, **kwargs):
        program = shlex.split(command)[2]
        printed = []
        exec(program, {"print": printed.append})
        return SimpleNamespace(returncode=0, stdout=printed[0], stderr="")

    result = check_linux_user_manager(run, secret_values=())
    assert result.error_code == USER_MANAGER_UNAVAILABLE
    assert result.evidence["recovery"] == user_manager_unavailable(
        BUS_ERROR, wsl=True, distro="Lab-Distro"
    )["recovery"]


@pytest.mark.parametrize(
    "returncode,code", [(255, SSH_UNAVAILABLE), (1, "linux_user_manager_probe_failed")]
)
def test_verify_names_an_unreadable_probe(returncode, code):
    result = check_linux_user_manager(
        lambda *a, **kw: SimpleNamespace(returncode=returncode, stdout="", stderr="secret x"),
        secret_values=("secret",),
    )
    assert not result.ok and result.evidence["stderr"] == "[REDACTED] x"
    assert result.error_code == code
