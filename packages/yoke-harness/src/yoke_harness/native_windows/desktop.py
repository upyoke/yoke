"""Run in the logged-on Windows test user's session, never SSH session zero."""

import base64
import hashlib
import json
import subprocess
import time
from uuid import uuid4

from yoke_contracts.machine_screenshot import screenshot_png
from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.native_windows.transport import quote


def desktop_script(control, script, *, timeout=60):
    token = uuid4().hex
    root = control.home + "\\AppData\\Local\\YokeQa\\" + token
    name = "YokeQa-" + token
    source, receipt = root + ".ps1", root + ".json"
    # The wrapper always writes a completion receipt, even for a script that
    # calls exit. Its child owns the exit code; only stdout/stderr are returned.
    child = root + ".command.ps1"
    control.upload_remote_text(child, script)
    control.upload_remote_text(
        source,
        f"""$ErrorActionPreference='Stop'
try {{
  & powershell.exe -NoLogo -NoProfile -File {quote(child)} 1> {quote(root + ".out")} 2> {quote(root + ".err")}
  $code=$LASTEXITCODE
  @{{exit_code=$code;stdout=[IO.File]::ReadAllText({quote(root + ".out")});stderr=[IO.File]::ReadAllText({quote(root + ".err")})}} |
    ConvertTo-Json -Compress | Set-Content -Encoding UTF8 {quote(receipt)}
}} catch {{ @{{exit_code=1;stdout='';stderr="$_"}} | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 {quote(receipt)} }}
""",
    )
    start = control._run(f"""$action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoLogo -NoProfile -WindowStyle Normal -File "'+{quote(source)}+'"')
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds {int(timeout)})
Register-ScheduledTask -TaskName {quote(name)} -Action $action -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName {quote(name)}
""")
    try:
        if start.returncode:
            return subprocess.CompletedProcess(
                [],
                69,
                "",
                "windows_desktop_task_unavailable: log on and unlock the test user; repair Task Scheduler permissions and retry",
            )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            text = control.read_remote_text(receipt)
            if text:
                row = json.loads(text.lstrip("\ufeff"))
                return subprocess.CompletedProcess(
                    [], int(row["exit_code"]), row["stdout"], row["stderr"]
                )
            time.sleep(0.2)
        return subprocess.CompletedProcess(
            [],
            124,
            "",
            "windows_desktop_task_timeout: unlock the auto-logged-on test session, inspect Task Scheduler and retry",
        )
    finally:
        cleanup = control._run(f"""if(Get-ScheduledTask -TaskName {quote(name)} -ErrorAction SilentlyContinue){{
  Stop-ScheduledTask -TaskName {quote(name)}
  Unregister-ScheduledTask -TaskName {quote(name)} -Confirm:$false
}}
Remove-Item -LiteralPath {",".join(quote(root + s) for s in (".ps1", ".command.ps1", ".json", ".out", ".err"))} -Force -ErrorAction SilentlyContinue
""")
        if cleanup.returncode:
            raise RuntimeError(
                "windows_desktop_cleanup_failed: stop and remove "
                + name
                + " in Task Scheduler before retrying"
            )


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
        captured = desktop_script(control, script, timeout=30)
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
