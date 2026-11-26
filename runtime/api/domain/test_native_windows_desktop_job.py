"""Desktop job receipt handling and native Win32 descendant custody."""

import json
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from yoke_harness.native_windows import desktop
from yoke_harness.native_windows.desktop_job import supervisor_script
from yoke_harness.native_windows.transport import quote


@pytest.mark.parametrize(
    ("phase", "code", "receipt", "cleanup"),
    [
        ("poll", 124, "verified_empty", "verified_absent"),
        ("poll", 124, "TerminateJobObject failed (Win32 5)", "unverified"),
        ("reconcile", 124, "verified_empty", "verified_absent"),
        ("reconcile", 124, "TerminateJobObject failed (Win32 5)", "unverified"),
        ("reconcile", 0, "verified_empty", "unverified"),
        ("reconcile", 124, None, "unverified"),
        ("writer_active", 124, None, "unverified"),
    ],
)
def test_desktop_timeout_requires_a_job_receipt(monkeypatch, phase, code, receipt, cleanup):
    body = json.dumps(
        {"exit_code": code, "stdout": "", "stderr": "owned timeout", "process_cleanup": receipt}
    ) if receipt else ""

    # Allow one poll and leave reconciliation four seconds of the existing grace.
    ticks = iter((0, 0, 17, 17))
    monkeypatch.setattr(desktop, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda _: None))
    scripts = []

    def run(script):
        scripts.append(script)
        if len(scripts) == 1:
            return subprocess.CompletedProcess([], 0, "", "")
        if phase == "writer_active":
            return subprocess.CompletedProcess([], 1, "", "sharing violation")
        return subprocess.CompletedProcess([], 0, body if phase == "reconcile" else "", "")

    control = SimpleNamespace(
        home=r"C:\Users\qa",
        upload_remote_text=lambda *_: None,
        read_remote_text=lambda _: body if phase == "poll" else None,
        _run=run,
    )
    result = desktop.desktop_script(control, "Start-Sleep 600", timeout=1)
    assert result.returncode == 124
    assert result.desktop_diagnostics["cleanup"] == cleanup
    assert "Remove-YokeTask 'YokeQa-" in scripts[-1]
    if phase != "poll":
        script = scripts[-1]
        assert "$clock.ElapsedMilliseconds -ge 4000" in script
        assert script.index("[IO.File]::Open") < script.index("[IO.File]::ReadAllText")
        assert script.index("[IO.File]::ReadAllText") < script.rindex("Remove-Item -LiteralPath")
        assert script.rindex("Remove-Item -LiteralPath") < script.rindex("$publisher.Dispose()")
    if receipt is None or code != 124:
        assert "windows_desktop_cleanup_unresolved" in result.stderr
        assert "recovery:" in result.stderr
        assert result.desktop_diagnostics["task"] in result.stderr
    else:
        assert result.stderr == "owned timeout"
        assert result.desktop_diagnostics["process_cleanup"] == receipt


@pytest.mark.windows_only(reason="Uses native file sharing and PowerShell publication")
def test_final_reconciliation_reads_late_receipt_after_publisher_exits(tmp_path):
    source = tmp_path / "producer.ps1"
    receipt = tmp_path / "receipt.json"
    ready = tmp_path / "ready"
    trigger = tmp_path / "trigger"
    staged = tmp_path / "receipt.tmp"
    cleanup = f"Remove-Item -LiteralPath {quote(str(source))},{quote(str(receipt))} -ErrorAction Stop"
    source.write_text(
        f"""$ErrorActionPreference='Stop'
$publisher=[IO.File]::Open($PSCommandPath, 'Open', 'Read', 'Read, Delete')
try {{
  New-Item -ItemType File -Path {quote(str(ready))} | Out-Null
  while (!(Test-Path -LiteralPath {quote(str(trigger))})) {{ Start-Sleep -Milliseconds 25 }}
  @{{exit_code=124;stdout='';stderr='timeout';process_cleanup='verified_empty'}} |
    ConvertTo-Json -Compress | Set-Content -Encoding UTF8 {quote(str(staged))}
  Move-Item -LiteralPath {quote(str(staged))} -Destination {quote(str(receipt))}
  Start-Sleep -Milliseconds 200
}} finally {{ $publisher.Dispose() }}
""",
        encoding="utf-8-sig",
    )
    reader = tmp_path / "reader.ps1"
    reader.write_text(
        f"New-Item -ItemType File -Path {quote(str(trigger))} | Out-Null\n"
        + desktop._reconcile_timeout(str(source), str(receipt), 3000, cleanup),
        encoding="utf-8-sig",
    )
    powershell = ["powershell.exe", "-NoProfile", "-File"]
    publisher = subprocess.Popen([*powershell, str(source)])
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert publisher.poll() is None and time.monotonic() < deadline
            time.sleep(0.05)
        result = subprocess.run(
            [*powershell, str(reader)], check=True, capture_output=True, text=True, timeout=10
        )
        assert json.loads(result.stdout)["process_cleanup"] == "verified_empty"
        assert not source.exists()
        assert not receipt.exists()
        assert publisher.wait(timeout=5) == 0
    finally:
        if publisher.poll() is None:
            publisher.terminate()
            publisher.wait(timeout=5)


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
