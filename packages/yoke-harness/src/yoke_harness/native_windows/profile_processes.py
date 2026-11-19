"""Stop processes that run from the resettable profile before the reset mirror.

A process started from the profile (the installed Yoke tool's Python, which
outlives the console install) holds its executable and DLLs open. Robocopy's
purge cannot delete open files, so the mirror leaves a half-removed uv Python
that fails the next install with uv exit 2.
"""

import json
from pathlib import PureWindowsPath

from yoke_harness.native_windows.transport import quote

STOPPED_MARKER = "YOKE_RESET_PROCESSES_STOPPED "

_LIST = r"""function Get-YokeProfileProcesses {
 foreach($proc in @(Get-Process -ErrorAction SilentlyContinue)){
  try {$exe=$proc.Path} catch {$exe=$null}
  if(!$exe -or !$exe.StartsWith($profileRoot+'\',[StringComparison]::OrdinalIgnoreCase)){continue}
  # Live identities and signed-in apps run from preserved directories.
  if(@($stopPreserved | Where-Object {$exe.StartsWith($_+'\',[StringComparison]::OrdinalIgnoreCase)}).Count){continue}
  [pscustomobject]@{id=$proc.Id;path=$exe}
 }
}
"""

_STOP = r"""$stopped=@(Get-YokeProfileProcesses)
# A process belongs to the logon that started it; SSH cannot end the desktop
# session's, so the reset first runs this script there too. taskkill's own
# refusal is not the verdict: the exit check below is.
foreach($proc in $stopped){cmd /c "taskkill /PID $($proc.id) /T /F >nul 2>&1"}
$deadline=[DateTime]::UtcNow.AddSeconds(20)
do {
 $alive=@($stopped | Where-Object {Get-Process -Id $_.id -ErrorAction SilentlyContinue})
 if(!$alive.Count){break}; Start-Sleep -Milliseconds 250
} while([DateTime]::UtcNow -lt $deadline)
if($alive.Count){
 throw ('windows_reset_profile_process_running: processes running from the test profile kept their files open: '+(($alive | ForEach-Object {[string]$_.id+' '+$_.path}) -join ', ')+'. End them from the signed-in test session (taskkill /PID ID /T /F), then rerun yoke test-machine reset')
}
Write-Output ('YOKE_RESET_PROCESSES_STOPPED '+(ConvertTo-Json -Compress -InputObject @($stopped | ForEach-Object {$_.path})))
"""


def _preamble(home, preserved):
    skipped = ",".join(quote(str(PureWindowsPath(home) / p)) for p in preserved)
    return f"$stopPreserved=@({skipped})\n" + _LIST


def profile_process_stop_script(home, preserved):
    """Run before the golden-to-profile mirror, with $profileRoot set."""
    return _preamble(home, preserved) + _STOP


def stop_desktop_profile_processes(control, preserved):
    """End profile processes from the signed-in session that owns them.

    Returns ``(refusal, stopped)``: the refusal text, or None when nothing ran
    from the profile or all of it ended, and the executables stopped. The
    reset script's own stop then verifies every session again.
    """
    from yoke_harness.native_windows.desktop import desktop_script

    home = f"$profileRoot={quote(control.home)}\n"
    listed = control._run(
        home + _preamble(control.home, preserved)
        + "if(@(Get-YokeProfileProcesses).Count){exit 3}; exit 0"
    )
    if listed.returncode == 0:
        return None, []
    if listed.returncode != 3:
        return listed.stderr or "windows_reset_profile_process_listing_failed: rerun yoke test-machine reset", []
    stopped = desktop_script(
        control, home + profile_process_stop_script(control.home, preserved),
        timeout=60, hidden=True,
    )
    if stopped.returncode:
        return stopped.stderr or stopped.stdout or "windows_reset_profile_process_running: the desktop stop failed without output; unlock the auto-logged-on test session and rerun yoke test-machine reset", []
    return None, stopped_processes(stopped.stdout)


def stopped_processes(stdout):
    """Read the executables the reset stopped from its standard output."""
    for line in (stdout or "").splitlines():
        if line.startswith(STOPPED_MARKER):
            return list(json.loads(line[len(STOPPED_MARKER):]) or [])
    return []
