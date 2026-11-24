import subprocess
from collections import deque
from types import SimpleNamespace

import pytest

from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness import ssh_native_windows_host_operations as operations
from yoke_harness.native_windows import console, console_reboot

BEFORE = "2026-11-24T12:00:00.0000000Z"
AFTER = "2026-11-24T12:30:00.0000000Z"
EMPTY = "YOKE_WINDOWS_SIGNED_OUT"


def completed(code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class Control:
    golden_baseline_path = r"C:\Golden"
    reset_installer_test_host = operations.SshNativeWindowsHostOperations.reset_installer_test_host

    def __init__(self):
        self.desktop = deque([completed(124, stderr="Original desktop failure")])
        self.detect = completed(stdout=EMPTY)
        self.boot = deque([completed(stdout=BEFORE), completed(stdout=AFTER)])
        self.shutdown = completed()
        self.calls = []
        self.clock = 0
        self.waits = []

    def _run(self, script, *, timeout=60):
        if script == console.SIGNED_OUT_PROBE:
            self.calls.append("detect")
            assert timeout == 20
            return self.detect
        if script == console_reboot.BOOT_TIME:
            self.calls.append("boot")
            assert 0 < timeout <= 20
            assert "GetTickCount64" in script
            assert not any(term in script.lower() for term in ("cim", "wmi"))
            return self.boot.popleft() if len(self.boot) > 1 else self.boot[0]
        if script == console_reboot.REBOOT:
            self.calls.append("shutdown")
            assert "shutdown.exe" in script and "/r /t 0 /d p:4:1" in script
            return self.shutdown
        assert "Get-Command yoke,yoke.cmd,uv,uvx" in script
        self.calls.append("path")
        return completed()

    def desktop_script(self, script, *, timeout, announce_wait=True):
        assert "[YokeDesktopGeometry]::Ensure()" in script
        assert timeout == 30
        assert announce_wait is ("shutdown" not in self.calls)
        self.calls.append("console")
        return self.desktop.popleft() if len(self.desktop) > 1 else self.desktop[0]

    def sleep(self, seconds):
        self.clock += seconds


@pytest.fixture
def control(monkeypatch):
    host = Control()
    monkeypatch.setattr(
        operations, "profile_operation",
        lambda *_args: HostActionResult(True, {"profile_restored": True}),
    )
    monkeypatch.setattr(
        console, "desktop_script", lambda host, *args, **kw: host.desktop_script(*args, **kw)
    )
    monkeypatch.setattr(
        console_reboot, "time",
        SimpleNamespace(monotonic=lambda: host.clock, sleep=host.sleep),
    )
    monkeypatch.setattr(
        console_reboot, "announce_designed_wait",
        lambda subject, **kw: host.waits.append((subject, kw)),
    )
    return host


@pytest.mark.parametrize("shutdown_code", [0, 124, 255])
def test_signed_out_reset_reboots_and_proves_console_before_path(control, shutdown_code):
    control.shutdown = completed(shutdown_code)
    control.desktop.extend([
        completed(124, stderr="Autologon still starting"),
        completed(stdout="1920x1080\n" + console.RECEIPT),
    ])

    result = control.reset_installer_test_host()

    assert result.ok
    assert result.evidence["profile_restored"]
    assert result.evidence["path_state"] == {"yoke_tools_resolve": False}
    assert result.evidence["console_reboot"] == {
        "boot_before": "2026-11-24T12:00:00+00:00",
        "boot_after": "2026-11-24T12:30:00+00:00",
        "elapsed_s": 10,
    }
    assert control.calls == [
        "console", "detect", "boot", "shutdown", "boot", "console", "console", "path"
    ]
    assert len(control.waits) == 1
    assert control.waits[0][1]["max_wait_seconds"] == 600


@pytest.mark.parametrize("detection", [
    completed(),  # A locked console or a connected/disconnected signed-in user.
    completed(1, EMPTY),
    completed(124),
    completed(stdout=EMPTY + "\nunexpected"),
    completed(stdout=EMPTY, stderr="Unexpected WTS warning"),
])
def test_reset_keeps_original_refusal_without_positive_signed_out_proof(control, detection):
    control.detect = detection

    result = control.reset_installer_test_host()

    assert result.error_code == "windows_console_not_ready"
    assert result.evidence["diagnostic"] == "Original desktop failure"
    assert control.calls == ["console", "detect"]
    assert not control.waits


@pytest.mark.parametrize("boot_after", [
    completed(stdout=BEFORE),
    completed(stdout="2026-11-24T12:00:30Z"),
    completed(255),
])
def test_reset_refuses_if_reboot_is_not_observed_before_deadline(control, boot_after):
    control.boot[-1] = boot_after

    result = control.reset_installer_test_host()

    assert result.error_code == "windows_console_not_ready"
    assert result.evidence["diagnostic"] == "reboot_not_observed"
    assert control.clock == 600
    assert control.calls.count("console") == control.calls.count("shutdown") == 1
    assert "path" not in control.calls


def test_reset_refuses_when_autologon_never_proves_console(control):
    result = control.reset_installer_test_host()

    assert result.error_code == "windows_console_not_ready"
    assert result.evidence["diagnostic"] == "console_not_ready_after_reboot"
    assert "VM console" in result.evidence["recovery"]
    assert control.clock == 600
    assert control.calls.count("console") > 2
    assert "path" not in control.calls


def test_reset_refuses_failed_shutdown_before_waiting(control):
    control.shutdown = completed(5, stderr="Access denied")

    result = control.reset_installer_test_host()

    assert result.error_code == "windows_console_not_ready"
    assert result.evidence["diagnostic"] == "reboot_refused"
    assert "SeShutdownPrivilege" in result.evidence["recovery"]
    assert control.calls == ["console", "detect", "boot", "shutdown"]
    assert not control.waits


def test_ready_console_needs_no_ssh_session_check_or_reboot(control):
    control.desktop[0] = completed(stdout="1920x1080\n" + console.RECEIPT)

    result = control.reset_installer_test_host()

    assert result.ok
    assert result.evidence["windows_console"]["resolution"] == "1920x1080"
    assert "console_reboot" not in result.evidence
    assert control.calls == ["console", "path"]
