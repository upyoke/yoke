"""Quiesce the test user's profile and packaged apps for a Windows reset."""

import json
import subprocess
from pathlib import PureWindowsPath

from yoke_harness.native_windows.transport import quote

STOPPED_MARKER = "YOKE_RESET_PROCESSES_STOPPED "
TARGETS_MARKER = "YOKE_RESET_DESKTOP_TARGETS "
RELAUNCHED_MARKER = "YOKE_RESET_DESKTOP_RELAUNCHED "

_LIST = r"""$windowsApps=Join-Path $env:ProgramFiles 'WindowsApps'
$testSid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$stopSession=(Get-Process -Id $PID).SessionId
function Get-YokeProfileProcesses {
 foreach($proc in @(Get-Process -ErrorAction SilentlyContinue)){
  try {$exe=$proc.Path} catch {$exe=$null}
  if(!$exe){continue}
  $packaged=$exe.StartsWith($windowsApps+'\',[StringComparison]::OrdinalIgnoreCase)
  if(!$packaged -and !$exe.StartsWith($profileRoot+'\',[StringComparison]::OrdinalIgnoreCase)){continue}
  if(@($stopPreserved | Where-Object {$exe.StartsWith($_+'\',[StringComparison]::OrdinalIgnoreCase)}).Count){continue}
  $instance=Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)" -ErrorAction Stop
  if(!$instance){continue}
  $owner=Invoke-CimMethod -InputObject $instance -MethodName GetOwnerSid -ErrorAction SilentlyContinue
  if($owner.ReturnValue -ne 0 -or $owner.Sid -ne $testSid){continue}
  [pscustomobject]@{process=$proc;path=$exe;packaged=$packaged}
 }
}
"""

_TARGETS = r"""$packages=@()
$packageFailure=''
if(@($stopped | Where-Object packaged).Count){
 try {$packages=@(Get-AppxPackage -ErrorAction Stop)} catch {$packageFailure=$_.Exception.Message}
}
$targets=@(foreach($entry in $stopped){
 $visible=$entry.process.MainWindowHandle -ne [IntPtr]::Zero
 if(!$entry.packaged){
  if($visible){@{target=$entry.path;path=$entry.path}}
  continue
 }
 try {
  if($packageFailure){throw $packageFailure}
  $package=$packages | Where-Object {
   $_.InstallLocation -and $entry.path.StartsWith($_.InstallLocation+'\',[StringComparison]::OrdinalIgnoreCase)
  } | Select-Object -First 1
  if($package){
   $manifest=Get-AppxPackageManifest -Package $package -ErrorAction Stop
   $apps=@($manifest.Package.Applications.Application | Where-Object Id)
   $matching=@($apps | Where-Object {
    $_.Executable -and (Join-Path $package.InstallLocation $_.Executable) -eq $entry.path
   })
   # A single-entry package can use a launcher stub ahead of its GUI process.
   if(!$matching.Count -and $visible -and $apps.Count -eq 1){$matching=$apps}
   foreach($app in $matching){
    @{target=('shell:AppsFolder\'+$package.PackageFamilyName+'!'+$app.Id);path=$entry.path}
   }
   if($matching.Count){continue}
  }
  if($visible){throw 'No unambiguous packaged app identity for this executable.'}
 } catch {
  if($visible){@{target=$entry.path;failure=$_.Exception.Message+' Open the app manually.'}}
 }
})
Write-Output ('YOKE_RESET_DESKTOP_TARGETS '+(ConvertTo-Json -Compress -InputObject $targets))
"""

_STOP = r"""# Stop selected processes individually so preserved children stay live.
foreach($entry in $stopped){
 Stop-Process -InputObject $entry.process -Force -ErrorAction SilentlyContinue
}
$deadline=[DateTime]::UtcNow.AddSeconds(20)
do {
 $alive=@($stopped | Where-Object {!$_.process.HasExited})
 if(!$alive.Count){break}; Start-Sleep -Milliseconds 250
} while([DateTime]::UtcNow -lt $deadline)
"""

_REFUSE = r"""if($alive.Count){
 throw ('windows_reset_profile_process_running: test-user processes kept their files open: '+(($alive | ForEach-Object {[string]$_.process.Id+' '+$_.path}) -join ', ')+'. End them from the signed-in test session, then rerun yoke test-machine reset')
}
Write-Output ('YOKE_RESET_PROCESSES_STOPPED '+(ConvertTo-Json -Compress -InputObject @($stopped | ForEach-Object {$_.path})))
"""

_RELAUNCH = r"""$stopSession=(Get-Process -Id $PID).SessionId
$pending=@(foreach($app in $apps){
 if($app.failure){Write-YokeRelaunchResult $app.target $app.failure; continue}
 try {
  if($app.target.StartsWith('shell:AppsFolder\')){
   Start-Process -FilePath explorer.exe -ArgumentList ('"'+$app.target+'"') -ErrorAction Stop
  } else {
   Start-Process -FilePath $app.target -WorkingDirectory (Split-Path -Parent $app.target) -ErrorAction Stop
  }
  $app
 } catch {
  Write-YokeRelaunchResult $app.target ($_.Exception.Message)
 }
})
# Explorer can accept the request even when package activation fails.
$deadline=[DateTime]::UtcNow.AddSeconds(20)
while($pending.Count){
 $running=@(Get-Process -ErrorAction SilentlyContinue | Where-Object {$_.SessionId -eq $stopSession} | ForEach-Object {
  try {$_.Path} catch {}
 })
 $pending=@(foreach($app in $pending){
  if($running -contains $app.path){Write-YokeRelaunchResult $app.target ''}
  elseif([DateTime]::UtcNow -ge $deadline){Write-YokeRelaunchResult $app.target 'No app process appeared in the desktop session; open it manually.'}
  else {$app}
 })
 if($pending.Count){Start-Sleep -Milliseconds 250}
}
"""

_RELAUNCH_RESULT = r"""function Write-YokeRelaunchResult($target,$failure){
 $record=@{target=$target;failure=$failure}
 # Emit receipts directly. They must not become members of the pending array.
 [Console]::WriteLine('YOKE_RESET_DESKTOP_RELAUNCHED '+(ConvertTo-Json -Compress -InputObject $record))
}
"""


def _preamble(home, preserved):
    skipped = ",".join(quote(str(PureWindowsPath(home) / p)) for p in preserved)
    return f"$stopPreserved=@({skipped})\n" + _LIST


def profile_process_stop_script(home, preserved, *, desktop=False):
    """Stop eligible processes in this session before the mirror."""
    return (
        "$ErrorActionPreference='Stop'\n"
        + _preamble(home, preserved)
        + "$stopped=@(Get-YokeProfileProcesses | Where-Object {$_.process.SessionId -eq $stopSession})\n"
        + (_TARGETS if desktop else "")
        + _STOP
        + ("" if desktop else "$alive=@($alive)+@(Get-YokeProfileProcesses)\n")
        + _REFUSE
    )


def stop_desktop_profile_processes(control, preserved):
    """End profile processes from the test user's signed-in session."""
    from yoke_harness.native_windows.desktop import desktop_script

    home = f"$profileRoot={quote(control.home)}\n"
    listed = control._run(
        "$ErrorActionPreference='Stop'\n" + home + _preamble(control.home, preserved)
        + "if(@(Get-YokeProfileProcesses).Count){exit 3}; exit 0"
    )
    if listed.returncode == 0:
        return None, [], []
    if listed.returncode != 3:
        return listed.stderr or "windows_reset_profile_process_listing_failed: rerun yoke test-machine reset", [], []
    stopped = desktop_script(
        control, home + profile_process_stop_script(control.home, preserved, desktop=True),
        timeout=60, hidden=True,
    )
    if stopped.returncode:
        return stopped.stderr or stopped.stdout or "windows_reset_profile_process_running: the desktop stop failed without output; unlock the auto-logged-on test session and rerun yoke test-machine reset", [], []
    targets = next(_records(stopped.stdout, TARGETS_MARKER), [])
    return None, stopped_processes(stopped.stdout), targets


def relaunch_desktop_apps(control, targets):
    """Refresh the desktop after reset and record each unique target's result."""
    from yoke_harness.native_windows.desktop import desktop_script

    unique = {app["target"].casefold(): app for app in targets}
    if not unique:
        return {"desktop_apps_relaunched": [], "desktop_apps_relaunch_failed": []}

    script = (
        "$apps=ConvertFrom-Json -InputObject " + quote(json.dumps(list(unique.values())))
        + "\n" + _RELAUNCH_RESULT + _RELAUNCH
    )
    try:
        result = desktop_script(control, script, timeout=60, hidden=True)
        receipts = {
            row["target"].casefold(): row["failure"]
            for row in _records(result.stdout, RELAUNCHED_MARKER)
        }
        missing = result.stderr or "Desktop relaunch returned no receipt; open the app manually."
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        receipts = {}
        missing = f"Desktop relaunch could not finish. Open the app manually. {exc}"

    relaunched, failed = [], []
    for key, app in unique.items():
        failure = receipts.get(key, missing)
        if failure:
            failed.append({"target": app["target"], "failure": failure})
        else:
            relaunched.append(app["target"])
    return {"desktop_apps_relaunched": relaunched, "desktop_apps_relaunch_failed": failed}


def _records(stdout, marker):
    for line in (stdout or "").splitlines():
        if line.startswith(marker):
            yield json.loads(line[len(marker):])


def stopped_processes(stdout):
    """Read the executables the reset stopped from its standard output."""
    return next(_records(stdout, STOPPED_MARKER), [])
