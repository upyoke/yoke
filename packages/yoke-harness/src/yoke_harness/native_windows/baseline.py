"""Capture and restore the native test profile without clearing sign-ins."""

from pathlib import PureWindowsPath

from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.native_windows.desktop import desktop_script
from yoke_harness.native_windows.transport import quote
from yoke_harness.native_windows.tasks import HELPERS as TASK_HELPERS
from yoke_harness.native_windows.profile_path import HELPERS as PATH_HELPERS
from yoke_harness.native_windows.mission import (
    WINDOWS_MISSION_SCRATCH_DIRECTORY, windows_stale_scratch_script,
)
from yoke_harness.native_windows.profile_processes import (
    profile_process_stop_script, relaunch_desktop_apps, stop_desktop_profile_processes, stopped_processes,
)
from yoke_harness.native_windows.profile_links import (
    link_sweep_record, stale_link_sweep_script,
)
from yoke_harness.native_windows.pristine import (
    RESIDUE_CLEANUP, STAGE_COPY_EXCLUSION, residue_refusal,
)


# Windows services and signed-in apps keep this state live outside the mirror.
PRESERVED_DIRECTORIES = (
    ".yoke-browser-identities",
    ".ssh",
    ".codex/packages",
    # The vendor's standalone launcher is a junction into those packages.
    "AppData/Local/Programs/OpenAI/Codex/bin",
    ".local/share/claude",
    ".local/share/cursor-agent",
    "AppData/Local/Microsoft",
    "AppData/Local/ConnectedDevicesPlatform",
    # The per-user data store service (UnistoreSvc) keeps its database open.
    "AppData/Local/Comms",
    "AppData/Local/Packages",
    "AppData/Local/Claude-Data",
    "AppData/Roaming/Microsoft",
    "AppData/Roaming/Claude",
    "AppData/Roaming/Cursor",
    "AppData/Local/Google",
    "AppData/Local/YokeQa",
    # A walk's secret staging outlives any reset inside the walk; walk-end
    # removes it, and reset removes other executions' (native_windows/mission.py).
    "AppData/Local/YokeQaMission",
    "AppData/Local/Temp",
)
# Cursor's Windows login file is %APPDATA%/cursor/auth.json, which the
# preserved AppData/Roaming/Cursor directory already keeps live.
PRESERVED_FILES = (
    ".claude/.credentials.json",
    ".codex/auth.json",
)


def golden_path(control, path):
    selected = PureWindowsPath(path)
    home = PureWindowsPath(control.home)
    if (
        not selected.is_absolute()
        or ".." in selected.parts
        or selected == home
        or home in selected.parents
        or selected in home.parents
        or len(selected.parts) < 3
    ):
        raise ValueError(
            "windows_golden_path_unsafe: choose a literal Windows golden directory outside the test profile"
        )
    return str(selected)


def profile_copy_script(control, destination):
    """Mirror resettable files while live app identities stay on the host."""
    path = golden_path(control, destination)
    excluded = ",".join(
        quote(str(PureWindowsPath(control.home) / p)) for p in PRESERVED_DIRECTORIES
    )
    # Exclude both source and destination paths: robocopy interprets /XD paths
    # relative to their respective trees when mirroring a restored profile.
    excluded_golden = ",".join(
        quote(str(PureWindowsPath(path) / "profile" / p)) for p in PRESERVED_DIRECTORIES
    )
    files = [
        str(PureWindowsPath(base) / value)
        for value in PRESERVED_FILES
        for base in (control.home, str(PureWindowsPath(path) / "profile"))
    ]
    excluded_files = ",".join(quote(value) for value in files)
    return f"""$exclude=@({excluded},{excluded_golden}); $files=@({excluded_files})
# The resident Codex sandbox service holds its provisioning guard during reset.
# Robocopy accepts literal paths here but rejects a wildcard in an absolute path.
foreach($root in @($source,$target)){{
 $codex=Join-Path $root '.codex'
 if(Test-Path -LiteralPath $codex -PathType Container){{
  $entry=Get-Item -LiteralPath $codex -Force
  if(!($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)){{
   $files+=@(Get-ChildItem -LiteralPath $codex -File -Force -Filter '.codex-provisioning-*.guard' |
     Select-Object -ExpandProperty FullName)
  }}
 }}
}}
{STAGE_COPY_EXCLUSION}# /MIR purges target links its source lacks, and goldens hold none (/XJ), so
# exclude Windows' own System-marked profile compatibility junctions.
$walk=New-Object System.Collections.Generic.Stack[string]; $walk.Push($target)
while($walk.Count){{
 $dir=$walk.Pop(); try {{$entries=@([IO.DirectoryInfo]::new($dir).GetFileSystemInfos())}} catch {{continue}}
 foreach($entry in $entries){{
  if($exclude -contains $entry.FullName){{continue}}
  $attributes=$entry.Attributes
  if($attributes -band [IO.FileAttributes]::ReparsePoint){{
   if(($attributes -band [IO.FileAttributes]::System) -and ($attributes -band [IO.FileAttributes]::Directory)){{$exclude+=$entry.FullName}}
  }} elseif($attributes -band [IO.FileAttributes]::Directory){{$walk.Push($entry.FullName)}}
 }}
}}
$logRoot=Join-Path $env:LOCALAPPDATA 'YokeQa'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$copyLog=Join-Path $logRoot ('profile-copy-'+[Guid]::NewGuid().ToString('N')+'.log')
& robocopy.exe $source $target /MIR /XJ /R:1 /W:1 /NP ('/LOG:'+$copyLog) /XD $exclude /XF $files NTUSER.DAT NTUSER.DAT.LOG* ntuser.ini UsrClass.dat* | Out-Null
$copyExit=$LASTEXITCODE
if($copyExit -ge 8){{
 # Name the failing files here: the log stays on the host, out of the caller's reach.
 $copyErrors=@(Select-String -LiteralPath $copyLog -Pattern 'ERROR \\d+ \\(0x' -Context 0,1 | Select-Object -First 8 | ForEach-Object {{($_.Line.Trim()+' '+(($_.Context.PostContext -join ' ').Trim())).Trim()}})
 $recovery='preserve the golden and repair the named copy failure before retrying'
 if(Select-String -LiteralPath $copyLog -Pattern 'ERROR (32|1224) \\(0x.*[\\\\/]\\.codex[\\\\/]' -Quiet){{
  $recovery='a running Codex app holds a .codex file open. Close Codex in the signed-in test session and rerun yoke test-machine reset'
 }}
 throw ('windows_profile_copy_failed: robocopy exit '+$copyExit+'; '+($copyErrors -join ' | ')+'; inspect private log '+$copyLog+'; '+$recovery)
}}
Remove-Item -LiteralPath $copyLog -Force
"""


def profile_script(control, operation, destination):
    path = golden_path(control, destination)
    preamble = TASK_HELPERS + PATH_HELPERS + f"$golden={quote(path)}; $profileRoot={quote(control.home)}; "
    preamble += r"""
$check=$golden
while($check){
 if(Test-Path -LiteralPath $check){
  $entry=Get-Item -LiteralPath $check -Force -ErrorAction Stop
  if($entry.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'windows_golden_link_unsafe: remove links from the golden path before capture or restore'}
 }
 $parent=Split-Path -Parent $check
 if($parent -eq $check){break}; $check=$parent
}
if(Test-Path -LiteralPath (Join-Path $golden 'profile')){
 if((Get-Item -LiteralPath (Join-Path $golden 'profile') -Force -ErrorAction Stop).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'windows_golden_link_unsafe: preserve the golden and remove its linked profile before restore'}
}
""".replace("\n+", "\n")
    copy = profile_copy_script(control, path)
    if operation == "capture":
        return (
            preamble
            + r"""if(Test-Path -LiteralPath $golden){throw 'windows_golden_exists: choose a new destination'}
New-Item -ItemType Directory -Path $golden | Out-Null
$source=$profileRoot; $target=Join-Path $golden 'profile'
"""
            + copy
            + r"""$tasks=@(Get-YokeOwnedTasks ($schedule.GetFolder('\')) | ForEach-Object {
  if($_.Definition.Principal.LogonType -notin @(2,3) -or $_.Definition.Principal.RunLevel -ne 0){
   throw 'windows_task_credentials_required: baseline tasks must use limited interactive or S4U logon without stored passwords'
  }
  $split=$_.Path.LastIndexOf('\')
  @{name=$_.Name;path=$_.Path.Substring(0,$split+1);xml=$_.Xml}
})
$pathKey=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment')
try {$pathSnapshot=Read-YokeUserPath $pathKey} finally {if($pathKey){$pathKey.Dispose()}}
@{user_path=[Environment]::GetEnvironmentVariable('Path','User');user_path_snapshot=$pathSnapshot;tasks=$tasks} |
 ConvertTo-Json -Depth 12 | Set-Content -Encoding UTF8 (Join-Path $golden 'state.json')
"""
        )
    return (
        preamble
        + r"""if(!(Test-Path -LiteralPath (Join-Path $golden 'sealed'))){throw 'windows_golden_unsealed: capture and register a sealed golden before reset'}
$state=Get-Content -Raw (Join-Path $golden 'state.json') | ConvertFrom-Json
Assert-YokeUserPath $state.user_path_snapshot
$source=Join-Path $golden 'profile'; $target=$profileRoot
"""
        + profile_process_stop_script(control.home, PRESERVED_DIRECTORIES)
        + copy
        + stale_link_sweep_script(control.home, PRESERVED_DIRECTORIES)
        + windows_stale_scratch_script(
            str(PureWindowsPath(control.home) / WINDOWS_MISSION_SCRATCH_DIRECTORY),
            tuple(getattr(control, "baseline_preserved_temp_paths", ())),
        )
        + RESIDUE_CLEANUP
        + r"""$pathKey=[Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
try {Restore-YokeUserPath $pathKey $state.user_path_snapshot} finally {$pathKey.Dispose()}
$env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')
$owned=@(Get-YokeOwnedTasks ($schedule.GetFolder('\')))
foreach($task in $owned){
 if(!($state.tasks | Where-Object {($_.path+$_.name) -eq $task.Path})){
  Remove-YokeTask $task.Path
 }
}
Get-ChildItem -LiteralPath (Join-Path $env:LOCALAPPDATA 'YokeQa') -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $env:TEMP -Force | Where-Object {
 $_.Name -match '^(yoke|playwright|chromium|pip)-' -and $_.FullName -ne $PSCommandPath
} | Remove-Item -Recurse -Force
foreach($task in $state.tasks){Restore-YokeTask $task}
"""
    )


def profile_operation(control, operation, path):
    try:
        script = profile_script(control, operation, path)
        desktop_stopped, targets = [], []
        if operation == "capture" and (refused := residue_refusal(control, operation)):
            return refused
        if operation == "reset":
            refused, desktop_stopped, targets = stop_desktop_profile_processes(
                control, PRESERVED_DIRECTORIES
            )
            if refused:
                return HostActionResult(
                    False,
                    {"operation": operation, "golden_baseline_path": path, "recovery": refused},
                    refused.split(":", 1)[0],
                )
        result = control._run(script, timeout=600)
    except ValueError as exc:
        return HostActionResult(
            False, {"recovery": str(exc)}, "windows_golden_path_unsafe"
        )
    ok = result.returncode == 0
    # The fresh-host absence proof: no stage folder or uv registry survives reset.
    residue = residue_refusal(control, operation) if ok and operation == "reset" else None
    relaunch = relaunch_desktop_apps(control, targets) if ok and operation == "reset" else {}
    restored = HostActionResult(
        ok,
        {
            "operation": operation,
            "golden_baseline_path": path,
            "profile": control.home,
            "preserved_identity_paths": list(PRESERVED_DIRECTORIES),
            **(
                {
                    "desktop_apps_relaunched": [],
                    **relaunch,
                    **link_sweep_record(result.stdout),
                    "profile_processes_stopped": desktop_stopped
                    + stopped_processes(result.stdout),
                }
                if operation == "reset"
                else {}
            ),
            **(
                {}
                if ok
                else {
                    "recovery": result.stderr
                    or "Repair the profile copy and retry; preserve the golden."
                }
            ),
        },
        None if ok else "windows_profile_" + operation + "_failed",
    )
    if residue:
        return HostActionResult(False, {**restored.evidence, **residue.evidence}, residue.error_code)
    return restored


INSTALL_OUTPUT_LINES = 40


def install_output(result):
    """Keep the end of both install streams: the installer's refusal lands on
    stderr while uv's own explanation streams to stdout."""
    parts = [
        f"install {label} (last {INSTALL_OUTPUT_LINES} lines):\n"
        + "\n".join(text.splitlines()[-INSTALL_OUTPUT_LINES:])
        for label, text in (("stderr", result.stderr), ("stdout", result.stdout))
        if (text or "").strip()
    ]
    return "\n".join(parts) or (
        f"The console install exited {result.returncode} without output; "
        "rerun it from the test user's desktop PowerShell to read its failure."
    )


def reach_baseline(control, name):
    if name not in {"fresh-host", "shell-preconfigured"}:
        raise ValueError("unknown native Windows baseline " + name)
    restored = control.reset_installer_test_host()
    if not restored.ok:
        return restored
    # Profile restore owns Windows temp cleanup: it empties AppData\Local\YokeQa
    # and Yoke-owned %TEMP% entries. A restored host must still prove it is the
    # signed-in user's machine, as macOS and Linux baselines do.
    proven = control.prove_user_equivalent()
    reset = {**restored.evidence, "user_equivalence": proven.evidence}
    if not proven.ok or name == "fresh-host":
        return HostActionResult(proven.ok, reset, proven.error_code)
    from yoke_contracts.machine_config import distribution, reader as machine_config

    origin = distribution.origin_for_connection(machine_config.active_connection())
    script = (
        "$ProgressPreference='SilentlyContinue'; "
        "$env:YOKE_INSTALL_YES='1'; $env:YOKE_NO_SETUP='1'; "
        f"$env:YOKE_INSTALL_BASE_URL={quote(origin)}; "
        f"$installer=Invoke-WebRequest -UseBasicParsing {quote(origin + '/install.ps1')}; "
        # install.ps1 echoes uv's output with Write-Host, the information
        # stream; merge it into stdout so the console task returns it.
        "& ([ScriptBlock]::Create($installer.Content)) --yes --no-setup 6>&1; "
        "if($LASTEXITCODE){exit $LASTEXITCODE}"
    )
    # Users install from a local PowerShell. sshd runs its sessions under
    # Redirection Guard, which blocks uv's Python junction (astral-sh/uv#19616),
    # so install as the signed-in desktop user; SSH only verifies.
    installed = desktop_script(control, script, timeout=1200)
    if installed.returncode:
        return HostActionResult(
            False,
            {
                "install_surface": "windows-console",
                "reset": reset,
                "recovery": install_output(installed),
            },
            "windows_baseline_install_failed",
        )
    probe = control.run_command([control.path_state.yoke_bin, "--version"])
    paths = {
        surface: control.path_state.tool_bin_dir.casefold()
        in {p.casefold() for p in control.probe_path(surface)}
        for surface in ("login", "ssh")
    }
    ok = probe.returncode == 0 and all(paths.values())
    return HostActionResult(
        ok,
        {
            "operation": name,
            "install_surface": "windows-console",
            "reset": reset,
            "path_state": paths,
            "launcher": control.path_state.yoke_bin,
        },
        None if ok else "windows_baseline_verification_failed",
    )
