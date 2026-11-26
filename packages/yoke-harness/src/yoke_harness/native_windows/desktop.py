"""Run in the logged-on Windows test user's session, never SSH session zero."""

import base64
import hashlib
import json
import subprocess
import time
from uuid import uuid4

from yoke_contracts.designed_wait import announce_designed_wait

from yoke_contracts.machine_screenshot import screenshot_png
from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.native_windows.desktop_job import (
    CLEANUP_SECONDS, RECOVERY, SCHEDULER_GRACE_SECONDS, TIMEOUT, UNRESOLVED, supervisor_script,
)
from yoke_harness.native_windows.transport import quote
from yoke_harness.native_windows.tasks import (
    create_interactive_task, remove_owned_task, require_task_result,
)


def desktop_script(control, script, *, timeout=60, hidden=False):
    token = uuid4().hex
    root = control.home + "\\AppData\\Local\\YokeQa\\" + token
    name = "YokeQa-" + token
    source, receipt = root + ".ps1", root + ".json"
    # The poll must never read a half-written receipt: publish it by rename.
    staged = receipt + ".tmp"
    # The wrapper always writes a completion receipt, even for a script that
    # calls exit. Its child owns the exit code; only stdout/stderr are returned.
    child = root + ".command.ps1"
    worker, worker_result = root + ".worker.ps1", root + ".worker.json"
    scheduler_timeout = timeout + SCHEDULER_GRACE_SECONDS
    # A hidden task must own no window: on a Windows Terminal host, even a
    # minimized console takes activation and dismisses the app's open menu.
    path = "conhost.exe" if hidden else "powershell.exe"
    launch = "--headless powershell.exe -NoLogo -NoProfile" if hidden else "-NoLogo -NoProfile -WindowStyle Normal"
    arguments = launch + ' -File "' + source + '"'
    # Windows PowerShell 5.1 wraps each native stderr line in an ErrorRecord;
    # under 'Stop' the first one would abort a command that succeeded, so the
    # child runs under 'Continue' and its streams are split by record type.
    command_worker = f"""$ErrorActionPreference='Stop'
try {{
  $ErrorActionPreference='Continue'
  $lines = @(& powershell.exe -NoLogo -NoProfile -File {quote(child)} 2>&1)
  $code=$LASTEXITCODE
  $ErrorActionPreference='Stop'
  $out = ($lines | Where-Object {{ $_ -isnot [Management.Automation.ErrorRecord] }} | ForEach-Object {{ "$_`n" }}) -join ''
  $err = ($lines | Where-Object {{ $_ -is [Management.Automation.ErrorRecord] }} | ForEach-Object {{ "$($_.Exception.Message)`n" }}) -join ''
  @{{exit_code=$code;stdout=$out;stderr=$err}} |
    ConvertTo-Json -Compress | Set-Content -Encoding UTF8 {quote(worker_result)}
}} catch {{ @{{exit_code=1;stdout='';stderr="$_"}} | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 {quote(worker_result)} }}
"""
    wrapper = supervisor_script(worker, worker_result, staged, receipt, timeout, name)
    payloads = ((child, script), (worker, command_worker), (source, wrapper))
    files = ",".join(quote(path) for path in (child, worker, worker_result, source, receipt, staged))
    diagnostics = {
        "desktop_token": token, "task": name,
        "files": [{"path": path, "sha256": hashlib.sha256(text.encode("utf-8-sig")).hexdigest(),
                   "bytes": len(text.encode("utf-8-sig"))}
                  for path, text in payloads],
        "phase": "upload", "cleanup": "pending",
    }
    completed_result = None

    def outcome(code, stdout, stderr):
        nonlocal completed_result
        completed_result = subprocess.CompletedProcess([], code, stdout, stderr)
        completed_result.desktop_diagnostics = diagnostics
        return completed_result

    failure = None
    uploads_complete = False
    try:
        for payload_path, text in payloads:
            control.upload_remote_text(payload_path, text)
        uploads_complete = True
        diagnostics["phase"] = "task_start"
        start = control._run(create_interactive_task(
            name, path, arguments, scheduler_timeout, getattr(control, "task_logon_type", 3)
        ))
        require_task_result(control, start, phase="desktop_task_start")
        announce_designed_wait("native Windows desktop task and cleanup", max_wait_seconds=scheduler_timeout)
        diagnostics["phase"] = "receipt"
        deadline = time.monotonic() + scheduler_timeout
        while time.monotonic() < deadline - CLEANUP_SECONDS:
            text = control.read_remote_text(receipt)
            if text:
                row = json.loads(text.lstrip("\ufeff"))
                if "process_cleanup" in row:
                    diagnostics["process_cleanup"] = row["process_cleanup"]
                return outcome(int(row["exit_code"]), row["stdout"], row["stderr"])
            time.sleep(0.2)
        diagnostics["process_cleanup"] = "missing desktop job receipt"
        return outcome(
            124,
            "",
            f"{TIMEOUT}: {UNRESOLVED}: task {name} published no verifiable job receipt; recovery: {RECOVERY}",
        )
    except BaseException as exc:
        failure = exc
        exc.desktop_diagnostics = diagnostics
        raise
    finally:
        try:
            if not uploads_complete and getattr(failure, "staging_diagnostics", {}).get("cleanup") == "preserved_ambiguous_execution":
                diagnostics["cleanup"] = "preserved_ambiguous_upload"
            elif not uploads_complete:
                # No task was started. Remove only payloads whose exact owner
                # and bytes still match this acquisition; preserve other files.
                checks = []
                for row in diagnostics["files"]:
                    checks.append(
                        "$p=" + quote(row["path"]) + ";if(Test-Path -LiteralPath $p){"
                        "$f=Get-Item -LiteralPath $p -Force -ErrorAction Stop;"
                        "if($f.PSIsContainer -or ($f.Attributes -band [IO.FileAttributes]::ReparsePoint) -or "
                        f"$f.Length -ne {row['bytes']} -or (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() -ne '{row['sha256']}' -or "
                        "(Get-Acl -LiteralPath $p).GetOwner([Security.Principal.SecurityIdentifier]).Value -ne [Security.Principal.WindowsIdentity]::GetCurrent().User.Value){throw 'Desktop acquisition bytes or owner changed; preserve'};"
                        "Remove-Item -LiteralPath $p -Force -ErrorAction Stop}"
                    )
                cleanup = control._run("\n".join(checks))
            else:
                removal = remove_owned_task(name).replace(
                    "Remove-YokeTask " + quote(name),
                    "$t=Get-YokeTask " + quote(name) + ";if($t -and ($t.Definition.Actions.Count -ne 1 -or $t.Definition.Actions.Item(1).Path -ne " + quote(path) + " -or $t.Definition.Actions.Item(1).Arguments -ne " + quote(arguments) + ")){throw 'Desktop task action changed; preserve'};Remove-YokeTask " + quote(name),
                )
                cleanup_script = removal + f"""
if(Get-YokeTask {quote(name)}){{throw 'Owned task cleanup incomplete'}}
Remove-Item -LiteralPath {files} -Force -ErrorAction SilentlyContinue
"""
                reconcile = diagnostics.get("process_cleanup") == "missing desktop job receipt"
                if completed_result is not None:
                    budget_ms = max(0, min(CLEANUP_SECONDS * 1000, int((deadline - time.monotonic()) * 1000)))
                    cleanup_script = _cleanup_after_publisher(
                        source, budget_ms, cleanup_script, receipt=receipt if reconcile else None
                    )
                # Windows completes deletion of the source after the last
                # handle closes. Check absence outside the guarded block.
                cleanup = control._run(cleanup_script + f"""
foreach($p in @({files})){{if(Test-Path -LiteralPath $p){{throw 'Owned desktop cleanup incomplete'}}}}
""")
                if reconcile and cleanup.stdout:
                    row = _read_timeout_receipt(cleanup.stdout)
                    if row is not None:
                        diagnostics["process_cleanup"] = row["process_cleanup"]
                        if row["process_cleanup"] == "verified_empty" or UNRESOLVED in row["stderr"]:
                            completed_result.stdout = row["stdout"]
                            completed_result.stderr = row["stderr"]
            if diagnostics["cleanup"] != "preserved_ambiguous_upload":
                process_cleanup = diagnostics.get("process_cleanup", "verified_empty")
                diagnostics["cleanup"] = (
                    "verified_absent" if cleanup.returncode == 0 and process_cleanup == "verified_empty"
                    else "unverified"
                )
                require_task_result(control, cleanup, phase="desktop_task_cleanup")
        except BaseException as exc:
            diagnostics["cleanup"] = "unverified"
            if failure is not None:
                failure.desktop_cleanup_cause = exc
            elif "process_cleanup" in diagnostics and isinstance(exc, Exception):
                diagnostics["task_cleanup_error"] = str(exc)
                completed_result.stderr += f"\nwindows_desktop_task_files_cleanup_failed: {exc}"
            else:
                exc.desktop_diagnostics = diagnostics
                raise


def _cleanup_after_publisher(source, budget_ms, cleanup, *, receipt=None):
    # The source is also the publisher's guard. Deny reading while cleaning
    # up, but allow deletion to prevent a delayed publisher from starting.
    ready = "$true"
    final_read = ""
    if receipt is not None:
        ready = f"(Test-Path -LiteralPath {quote(receipt)}) -or $clock.ElapsedMilliseconds -ge {budget_ms}"
        final_read = f"""
  if (Test-Path -LiteralPath {quote(receipt)}) {{
    $entry=Get-Item -LiteralPath {quote(receipt)} -Force
    if ($entry.PSIsContainer -or ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        (Get-Acl -LiteralPath $entry.FullName).GetOwner([Security.Principal.SecurityIdentifier]).Value -ne
        [Security.Principal.WindowsIdentity]::GetCurrent().User.Value) {{
      throw 'Desktop timeout receipt ownership could not be established; preserve it'
    }}
    [IO.File]::ReadAllText($entry.FullName)
  }}
"""
    return f"""$ErrorActionPreference='Stop'
$clock=[Diagnostics.Stopwatch]::StartNew()
$publisher=$null
do {{
  if ({ready}) {{
    try {{ $publisher=[IO.File]::Open({quote(source)}, 'Open', 'Read', 'Delete') }}
    catch {{
      # ERROR_SHARING_VIOLATION means the publisher still has the guard.
      if ($_.Exception.GetBaseException().HResult -ne -2147024864 -or
          $clock.ElapsedMilliseconds -ge {budget_ms}) {{ throw }}
    }}
    if ($null -ne $publisher) {{ break }}
  }}
  Start-Sleep -Milliseconds 50
}} while ($true)
try {{
{final_read}{cleanup}
}} finally {{ $publisher.Dispose() }}
"""


def _read_timeout_receipt(text):
    try:
        row = json.loads(text.lstrip("\ufeff"))
    except ValueError:
        return None
    if (
        isinstance(row, dict) and row.get("exit_code") == 124
        and all(isinstance(row.get(key), str) for key in ("stdout", "stderr", "process_cleanup"))
    ):
        return row
    return None


def capture_desktop(control, *, focused_window=False):
    remote = control.home + r"\AppData\Local\YokeQa\desktop-" + uuid4().hex + ".png"
    script = r"""Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$bounds=[Windows.Forms.SystemInformation]::VirtualScreen
$image=[Drawing.Bitmap]::new($bounds.Width,$bounds.Height)
$graphics=[Drawing.Graphics]::FromImage($image)
try {
  $graphics.CopyFromScreen($bounds.Location,[Drawing.Point]::Empty,$bounds.Size)
  $image.Save(DESTINATION,[Drawing.Imaging.ImageFormat]::Png)
} finally { $graphics.Dispose(); $image.Dispose() }
""".replace("DESTINATION", quote(remote))
    if focused_window:
        return HostActionResult(
            False,
            {"recovery": "Request a full native desktop capture."},
            "windows_focused_capture_unsupported",
        )
    try:
        captured = desktop_script(control, script, timeout=30, hidden=True)
        if captured.returncode:
            return HostActionResult(
                False, {"recovery": captured.stderr}, "windows_desktop_capture_failed"
            )
        read = control._run(
            f"[Convert]::ToBase64String([IO.File]::ReadAllBytes({quote(remote)}))"
        )
        if read.returncode:
            raise ValueError(
                "windows_screenshot_read_failed: repair the screenshot file ACL and retry"
            )
        content, (width, height) = screenshot_png(read.stdout.strip())
        return HostActionResult(
            True,
            {
                "os": "windows",
                "desktop_session": "interactive",
                "capture_scope": "desktop",
                "sha256": hashlib.sha256(content).hexdigest(),
                "width": width,
                "height": height,
                "artifact_token": "desktop",
                "capture_artifact": {
                    "token": "desktop",
                    "filename": "desktop.png",
                    "content_type": "image/png",
                    "content_base64": base64.b64encode(content).decode("ascii"),
                },
            },
        )
    except (ValueError, RuntimeError) as exc:
        return HostActionResult(
            False, {"recovery": str(exc)}, "windows_desktop_capture_failed"
        )
    finally:
        control._run(
            f"Remove-Item -LiteralPath {quote(remote)} -Force -ErrorAction SilentlyContinue"
        )
