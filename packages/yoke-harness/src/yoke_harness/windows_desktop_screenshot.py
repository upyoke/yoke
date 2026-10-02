"""Capture the Windows SSH account's interactive desktop from its WSL2 shell."""

from __future__ import annotations

import base64
import json
import shlex


CAPTURE_SCRIPT = r"""$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$directory = 'OUTPUT_DIRECTORY'
try {
    if ([Diagnostics.Process]::GetCurrentProcess().SessionId -eq 0) {
        throw 'windows_desktop_session_required: repair the registered FreeRDP login and retry the screenshot; a human RDP login is the fallback'
    }
    if (Get-Process LogonUI -ErrorAction SilentlyContinue | Where-Object SessionId -eq ([Diagnostics.Process]::GetCurrentProcess().SessionId)) {
        throw 'windows_desktop_locked: unlock the active dedicated desktop and retry'
    }
    Add-Type -AssemblyName System.Windows.Forms,System.Drawing
    $bounds = [Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bitmap = New-Object Drawing.Bitmap $bounds.Width,$bounds.Height
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($bounds.Location,[Drawing.Point]::Empty,$bounds.Size)
        $bitmap.Save((Join-Path $directory 'desktop.png'),[Drawing.Imaging.ImageFormat]::Png)
        @{ok=$true;session_id=[Diagnostics.Process]::GetCurrentProcess().SessionId} |
            ConvertTo-Json -Compress | Set-Content (Join-Path $directory 'result.pending.json')
    } finally { $graphics.Dispose(); $bitmap.Dispose() }
} catch {
    @{ok=$false;error=$_.Exception.Message} | ConvertTo-Json -Compress |
        Set-Content (Join-Path $directory 'result.pending.json')
}
Move-Item -LiteralPath (Join-Path $directory 'result.pending.json') -Destination (Join-Path $directory 'result.json')
"""


TASK_SCRIPT = r"""$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$name = 'YokeDesktop-' + [Guid]::NewGuid().ToString('N')
$directory = Join-Path $env:TEMP $name
$registered = $false
try {
    New-Item -ItemType Directory -Path $directory | Out-Null
    $capture = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('CAPTURE_BASE64'))
    $capture = $capture.Replace('OUTPUT_DIRECTORY',$directory.Replace("'","''"))
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($capture))
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -EncodedCommand ' + $encoded)
    $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $name -Action $action -Principal $principal | Out-Null
    $registered = $true
    Start-ScheduledTask -TaskName $name
    $resultPath = Join-Path $directory 'result.json'
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while (!(Test-Path -LiteralPath $resultPath)) {
        if ([DateTime]::UtcNow -ge $deadline) {
            throw 'windows_desktop_session_required: register the same Windows user for SSH and desktop access, verify FreeRDP can open its unlocked desktop, then retry'
        }
        Start-Sleep -Milliseconds 200
    }
    $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    if (!$result.ok) { throw ('windows_desktop_capture_failed: ' + $result.error) }
    @{content_base64=[Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $directory 'desktop.png')));session_id=$result.session_id} | ConvertTo-Json -Compress
} catch {
    @{ok=$false;recovery=$_.Exception.Message} | ConvertTo-Json -Compress
} finally {
    if ($registered) {
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }
    if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force }
}
"""


def windows_desktop_png(control) -> tuple[str, int]:
    """Capture with the interactive token held by the Windows session owner."""
    script = TASK_SCRIPT.replace(
        "CAPTURE_BASE64", base64.b64encode(CAPTURE_SCRIPT.encode()).decode("ascii")
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = control._run(
        "powershell.exe -NoProfile -NonInteractive -EncodedCommand "
        + shlex.quote(encoded),
        timeout=45,
    )
    if result.returncode:
        raise RuntimeError(
            "windows_desktop_capture_failed: verify the registered SSH account's held RDP desktop and retry; "
            + result.stderr[-1000:]
        )
    try:
        payload = json.loads(result.stdout.lstrip("\ufeff"))
        if payload.get("ok") is False:
            raise RuntimeError(payload["recovery"])
        session_id = int(payload["session_id"])
        if session_id <= 0:
            raise ValueError("non-interactive session")
        return payload["content_base64"], session_id
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "windows_desktop_capture_invalid: repair the interactive task's PNG response and retry"
        ) from exc
