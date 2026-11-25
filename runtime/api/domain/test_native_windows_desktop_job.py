"""Desktop job receipt handling and native Win32 descendant custody."""

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_harness.native_windows import desktop
from yoke_harness.native_windows.desktop_job import supervisor_script
from yoke_harness.native_windows.transport import quote


@pytest.mark.parametrize(
    ("receipt", "cleanup"),
    [
        ("verified_empty", "verified_absent"),
        ("TerminateJobObject failed (Win32 5)", "unverified"),
        (None, "unverified"),
    ],
)
def test_desktop_timeout_requires_a_job_receipt(monkeypatch, receipt, cleanup):
    def read_remote_text(_path):
        if receipt is not None:
            return json.dumps(
                {"exit_code": 124, "stdout": "", "stderr": "timeout", "process_cleanup": receipt}
            )
        return None

    # Allow one poll, then expire the controller's grace period.
    ticks = iter((0, 0, 22))
    monkeypatch.setattr(desktop, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _: None))
    scripts = []
    control = SimpleNamespace(
        home=r"C:\Users\qa",
        upload_remote_text=lambda *_: None,
        read_remote_text=read_remote_text,
        _run=lambda script: scripts.append(script) or subprocess.CompletedProcess([], 0, "", ""),
    )
    result = desktop.desktop_script(control, "Start-Sleep 600", timeout=1)
    assert result.returncode == 124
    assert result.desktop_diagnostics["cleanup"] == cleanup
    assert "Remove-YokeTask 'YokeQa-" in scripts[-1]
    if receipt is None:
        assert "windows_desktop_cleanup_unresolved" in result.stderr
        assert "recovery:" in result.stderr
        assert result.desktop_diagnostics["task"] in result.stderr
    else:
        assert result.desktop_diagnostics["process_cleanup"] == receipt


@pytest.mark.windows_only(reason="Runs the Windows PowerShell supervisor against the Win32 Job API")
@pytest.mark.parametrize("timeout", [False, True], ids=["handoff", "timeout"])
def test_native_desktop_job_tree(tmp_path, timeout):
    import psutil

    def write(name, source):
        path = tmp_path / name
        path.write_text(source, encoding="utf-8-sig")
        return str(path)

    def pid_file(name):
        return tmp_path / name

    grandchild = write(
        "grandchild.ps1",
        f"Set-Content -LiteralPath {quote(str(pid_file('grandchild.pid')))} -Value $PID; Start-Sleep 120",
    )
    child = write(
        "child.ps1",
        f"Set-Content -LiteralPath {quote(str(pid_file('child.pid')))} -Value $PID\n"
        f"Start-Process powershell.exe ('-NoProfile -File \"' + {quote(grandchild)} + '\"')\n"
        "Start-Sleep 120",
    )
    worker_result = str(tmp_path / "worker.json")
    receipt = tmp_path / "receipt.json"
    worker = write(
        "worker.ps1",
        "$ErrorActionPreference='Stop'\n"
        f"Start-Process powershell.exe ('-NoProfile -File \"' + {quote(child)} + '\"')\n"
        f"while(!(Test-Path -LiteralPath {quote(str(pid_file('grandchild.pid'))) }))"
        "{Start-Sleep -Milliseconds 50}\n"
        + (
            "Start-Sleep 120"
            if timeout
            else f"""Set-Content -LiteralPath {quote(worker_result)} -Value '{{"exit_code":0}}'"""
        ),
    )
    supervisor = write(
        "task.ps1",
        supervisor_script(worker, worker_result, str(tmp_path / "staged.json"), str(receipt), 10, "test"),
    )
    control = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    def fixture_process(pid, script):
        try:
            process = psutil.Process(pid)
            return process if script in process.cmdline() else None
        except psutil.NoSuchProcess:
            return None

    fixture = (("child.pid", child), ("grandchild.pid", grandchild))
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-File", supervisor], check=True, timeout=25)
        row = json.loads(receipt.read_text(encoding="utf-8-sig"))
        members = [fixture_process(int(pid_file(name).read_text()), script) for name, script in fixture]
        assert control.poll() is None
        if timeout:
            assert row["exit_code"] == 124
            assert row["process_cleanup"] == "verified_empty"
            assert "Windows Job confirmed empty" in row["stderr"]
            assert not any(members)
        else:
            assert row["exit_code"] == 0
            assert all(members)
    finally:
        if control.poll() is None:
            control.terminate()
            control.wait(timeout=5)
        for name, script in fixture:
            path = pid_file(name)
            if path.exists() and path.read_text().strip():
                member = fixture_process(int(path.read_text()), script)
                if member is not None:
                    member.terminate()
                    member.wait(timeout=5)
