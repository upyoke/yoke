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

_STOP = r"""function Get-YokeProfileProcesses {
 foreach($proc in @(Get-Process -ErrorAction SilentlyContinue)){
  try {$exe=$proc.Path} catch {$exe=$null}
  if(!$exe -or !$exe.StartsWith($profileRoot+'\',[StringComparison]::OrdinalIgnoreCase)){continue}
  # Live identities and signed-in apps run from preserved directories.
  if(@($stopPreserved | Where-Object {$exe.StartsWith($_+'\',[StringComparison]::OrdinalIgnoreCase)}).Count){continue}
  [pscustomobject]@{id=$proc.Id;path=$exe}
 }
}
$stopped=@(Get-YokeProfileProcesses)
foreach($proc in $stopped){& taskkill.exe /PID $proc.id /T /F 2>&1 | Out-Null}
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


def profile_process_stop_script(home, preserved):
    """Run before the golden-to-profile mirror, with $profileRoot set."""
    skipped = ",".join(quote(str(PureWindowsPath(home) / p)) for p in preserved)
    return f"$stopPreserved=@({skipped})\n" + _STOP


def stopped_processes(stdout):
    """Read the executables the reset stopped from its standard output."""
    for line in (stdout or "").splitlines():
        if line.startswith(STOPPED_MARKER):
            return list(json.loads(line[len(STOPPED_MARKER):]) or [])
    return []
