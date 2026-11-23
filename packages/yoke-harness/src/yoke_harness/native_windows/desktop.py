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
    # A hidden task must own no window: on a Windows Terminal host, even a
    # minimized console takes activation and dismisses the app's open menu.
    path = "conhost.exe" if hidden else "powershell.exe"
    launch = "--headless powershell.exe -NoLogo -NoProfile" if hidden else "-NoLogo -NoProfile -WindowStyle Normal"
    arguments = launch + ' -File "' + source + '"'
    # Windows PowerShell 5.1 wraps each native stderr line in an ErrorRecord;
    # under 'Stop' the first one would abort a command that succeeded, so the
    # child runs under 'Continue' and its streams are split by record type.
    wrapper = f"""$ErrorActionPreference='Stop'
try {{
  $ErrorActionPreference='Continue'
  $lines = @(& powershell.exe -NoLogo -NoProfile -File {quote(child)} 2>&1)
  $code=$LASTEXITCODE
  $ErrorActionPreference='Stop'
  $out = ($lines | Where-Object {{ $_ -isnot [Management.Automation.ErrorRecord] }} | ForEach-Object {{ "$_`n" }}) -join ''
  $err = ($lines | Where-Object {{ $_ -is [Management.Automation.ErrorRecord] }} | ForEach-Object {{ "$($_.Exception.Message)`n" }}) -join ''
  @{{exit_code=$code;stdout=$out;stderr=$err}} |
    ConvertTo-Json -Compress | Set-Content -Encoding UTF8 {quote(staged)}
  Move-Item -LiteralPath {quote(staged)} -Destination {quote(receipt)} -Force
}} catch {{ @{{exit_code=1;stdout='';stderr="$_"}} | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 {quote(staged)}; Move-Item -LiteralPath {quote(staged)} -Destination {quote(receipt)} -Force }}
"""
    diagnostics = {
        "desktop_token": token, "task": name,
        "files": [{"path": path, "sha256": hashlib.sha256(text.encode("utf-8-sig")).hexdigest(),
                   "bytes": len(text.encode("utf-8-sig"))}
                  for path, text in ((child, script), (source, wrapper))],
        "phase": "upload", "cleanup": "pending",
    }
    def outcome(code, stdout, stderr):
        result = subprocess.CompletedProcess([], code, stdout, stderr)
        result.desktop_diagnostics = diagnostics
        return result

    failure = None
    uploads_complete = False
    try:
        control.upload_remote_text(child, script)
        control.upload_remote_text(source, wrapper)
        uploads_complete = True
        diagnostics["phase"] = "task_start"
        start = control._run(create_interactive_task(name, path, arguments, timeout))
        require_task_result(control, start, phase="desktop_task_start")
        announce_designed_wait("native Windows desktop task", max_wait_seconds=timeout)
        diagnostics["phase"] = "receipt"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            text = control.read_remote_text(receipt)
            if text:
                row = json.loads(text.lstrip("\ufeff"))
                return outcome(int(row["exit_code"]), row["stdout"], row["stderr"])
            time.sleep(0.2)
        return outcome(
            124,
            "",
            "windows_desktop_task_timeout: unlock the auto-logged-on test session, inspect Task Scheduler and retry",
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
                cleanup = control._run(removal + f"\nif(Get-YokeTask {quote(name)}){{throw 'Owned task cleanup incomplete'}}\nRemove-Item -LiteralPath {','.join(quote(root + s) for s in ('.ps1', '.command.ps1', '.json', '.json.tmp'))} -Force -ErrorAction SilentlyContinue; foreach($p in @({','.join(quote(root + s) for s in ('.ps1', '.command.ps1', '.json', '.json.tmp'))})){{if(Test-Path -LiteralPath $p){{throw 'Owned desktop cleanup incomplete'}}}}")
            if diagnostics["cleanup"] != "preserved_ambiguous_upload":
                diagnostics["cleanup"] = "verified_absent" if cleanup.returncode == 0 else "unverified"
                require_task_result(control, cleanup, phase="desktop_task_cleanup")
        except BaseException as exc:
            diagnostics["cleanup"] = "unverified"
            if failure is not None:
                failure.desktop_cleanup_cause = exc
            else:
                exc.desktop_diagnostics = diagnostics
                raise


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
