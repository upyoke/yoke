"""Quiesce the test user's profile and packaged apps for a Windows reset."""

import json
import re
import subprocess
from pathlib import PureWindowsPath

from yoke_harness.native_windows.transport import quote

DISCOVERY_MARKER = "YOKE_RESET_PROCESS_DISCOVERY "
STOPPED_MARKER = "YOKE_RESET_PROCESSES_STOPPED "
TARGETS_MARKER = "YOKE_RESET_DESKTOP_TARGETS "
RELAUNCHED_MARKER = "YOKE_RESET_DESKTOP_RELAUNCHED "

# Shell packages Windows restarts on its own within seconds of a stop. Stopping
# them cannot hold, and the Widgets board has no window to relaunch. Their state
# lives under the preserved AppData/Local/Packages, so they hold no files in the
# mirrored profile; a lock there would still fail robocopy loudly.
SHELL_RESTARTED_PACKAGES = (
    ("MicrosoftWindows.Client.WebExperience", "cw5n1h2txyewy"),
    ("Microsoft.WidgetsPlatformRuntime", "8wekyb3d8bbwe"),
    ("Microsoft.StartExperiencesApp", "8wekyb3d8bbwe"),
)

# The SSH test user has no WMI namespace grant. Limited process handles can
# read the owner's token and image without elevation or reading process memory.
_PROCESS_IDENTITY = r"""Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;

public static class YokeResetProcess {
 [DllImport("kernel32.dll")] static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
 [DllImport("advapi32.dll")] static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode)]
 static extern bool QueryFullProcessImageName(IntPtr process, int flags, StringBuilder name, ref int size);

 public static string OwnedImage(int pid, string owner) {
  IntPtr process=OpenProcess(0x1000, false, pid); // PROCESS_QUERY_LIMITED_INFORMATION
  if(process==IntPtr.Zero) return null;
  IntPtr token=IntPtr.Zero;
  try {
   if(!OpenProcessToken(process, 8, out token)) return null; // TOKEN_QUERY
   using(var identity=new WindowsIdentity(token)) {
    if(identity.User.Value!=owner) return null;
   }
   var path=new StringBuilder(32768);
   int size=path.Capacity;
   return QueryFullProcessImageName(process, 0, path, ref size) ? path.ToString() : null;
  } finally {
   if(token!=IntPtr.Zero) CloseHandle(token);
   CloseHandle(process);
  }
 }
}
'@
$testSid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
function Get-YokeOwnedExecutable($processId){
 [YokeResetProcess]::OwnedImage($processId, $testSid)
}
if(!(Get-YokeOwnedExecutable $PID)){throw 'Cannot verify ownership of the reset process'}
"""

_LIST = r"""$windowsApps=Join-Path $env:ProgramFiles 'WindowsApps'
$stopSession=(Get-Process -Id $PID).SessionId
function Get-YokeProfileProcesses {
 foreach($proc in @(Get-Process -ErrorAction Stop)){
  $exe=Get-YokeOwnedExecutable $proc.Id
  if(!$exe){continue}
  $packaged=$exe.StartsWith($windowsApps+'\',[StringComparison]::OrdinalIgnoreCase)
  if(!$packaged -and !$exe.StartsWith($profileRoot+'\',[StringComparison]::OrdinalIgnoreCase)){continue}
  if(@($stopPreserved | Where-Object {$exe.StartsWith($_+'\',[StringComparison]::OrdinalIgnoreCase)}).Count){continue}
  if($packaged -and $exe.Substring($windowsApps.Length+1).Split('\')[0] -match $shellRestarted){continue}
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
 try {$visible=$entry.process.MainWindowHandle -ne [IntPtr]::Zero} catch {$visible=$false}
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
 $alive=@($stopped | Where-Object {
  $entry=$_
  try {!$entry.process.HasExited} catch {
   (Get-YokeOwnedExecutable $entry.process.Id) -eq $entry.path
  }
 })
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
    return (
        f"$stopPreserved=@({skipped})\n$shellRestarted={quote(_shell_restarted_pattern())}\n"
        + _PROCESS_IDENTITY + _LIST
    )


def _shell_restarted_pattern():
    # A WindowsApps directory is Name_Version_Arch_ResourceId_PublisherId.
    names = "|".join(
        f"{re.escape(name)}_.+_{publisher}" for name, publisher in SHELL_RESTARTED_PACKAGES
    )
    return f"^(?:{names})$"


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


def profile_process_discovery_script(home, preserved):
    # The verified staging wrapper can collapse a child script's nonzero
    # exit status. Use a receipt for both successful discovery outcomes.
    return (
        "$ErrorActionPreference='Stop'\n"
        + f"$profileRoot={quote(home)}\n" + _preamble(home, preserved)
        + f"if(@(Get-YokeProfileProcesses).Count){{'{DISCOVERY_MARKER}present'}}"
        + f"else{{'{DISCOVERY_MARKER}empty'}}"
    )


def stop_desktop_profile_processes(control, preserved):
    """End profile processes from the test user's signed-in session."""
    from yoke_harness.native_windows.desktop import desktop_script

    listed = control._run(profile_process_discovery_script(control.home, preserved))
    answers = [
        line[len(DISCOVERY_MARKER):] for line in (listed.stdout or "").splitlines()
        if line.startswith(DISCOVERY_MARKER)
    ]
    if listed.returncode or answers not in (["present"], ["empty"]):
        detail = (listed.stderr or "").strip()
        if not detail:
            detail = (listed.stdout or "").strip() if listed.returncode else ""
            detail = detail or (
                f"exit {listed.returncode}" if listed.returncode else "missing or invalid discovery receipt"
            )
        return (
            f"windows_reset_profile_process_listing_failed: SSH process discovery failed: {detail}. "
            "Verify the standard test-user SSH session and rerun yoke test-machine reset",
            [], [],
        )
    if answers == ["empty"]:
        return None, [], []
    home = f"$profileRoot={quote(control.home)}\n"
    stopped = desktop_script(
        control, home + profile_process_stop_script(control.home, preserved, desktop=True),
        timeout=60, hidden=True,
    )
    if stopped.returncode:
        detail = (stopped.stderr or stopped.stdout or f"exit {stopped.returncode}").strip()
        return (
            f"windows_reset_profile_process_running: Desktop process stop failed: {detail}. "
            "Inspect the signed-in standard-user desktop and rerun yoke test-machine reset",
            [], [],
        )
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
