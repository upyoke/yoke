"""Capture and restore the native test profile without clearing sign-ins."""

from pathlib import PureWindowsPath

from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.native_windows.transport import quote


# These contain live Windows credentials, browser identities or locked registry
# hives. They stay on this dedicated user, never travel through a receipt.
PRESERVED_DIRECTORIES = (
    ".yoke-browser-identities",
    ".ssh",
    ".codex/packages",
    ".local/share/claude",
    ".local/share/cursor-agent",
    "AppData/Local/Microsoft",
    "AppData/Roaming/Microsoft",
    "AppData/Roaming/Claude",
    "AppData/Roaming/Cursor",
    "AppData/Local/Google",
    "AppData/Local/YokeQa",
)
PRESERVED_FILES = (
    ".claude/.credentials.json",
    ".codex/auth.json",
    ".config/cursor/auth.json",
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


def profile_script(control, operation, destination):
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
    preamble = f"$golden={quote(path)}; $profileRoot={quote(control.home)}; "
    copy = f"""$exclude=@({excluded},{excluded_golden}); $files=@({excluded_files})
& robocopy.exe $source $target /MIR /XJ /R:1 /W:1 /XD $exclude /XF $files NTUSER.DAT NTUSER.DAT.LOG* ntuser.ini UsrClass.dat* | Out-Null
if($LASTEXITCODE -ge 8){{throw 'windows_profile_copy_failed: close test applications and retry; the golden was not sealed'}}
"""
    if operation == "capture":
        return (
            preamble
            + r"""if(Test-Path -LiteralPath $golden){throw 'windows_golden_exists: choose a new destination'}
New-Item -ItemType Directory -Path $golden | Out-Null
$source=$profileRoot; $target=Join-Path $golden 'profile'
"""
            + copy
            + r"""$tasks=@(Get-ScheduledTask | Where-Object {$_.Principal.UserId -in @($env:USERNAME,[Security.Principal.WindowsIdentity]::GetCurrent().Name)} | ForEach-Object {
  @{name=$_.TaskName;path=$_.TaskPath;xml=(Export-ScheduledTask -TaskName $_.TaskName -TaskPath $_.TaskPath)}
})
@{user_path=[Environment]::GetEnvironmentVariable('Path','User');tasks=$tasks} |
 ConvertTo-Json -Depth 12 | Set-Content -Encoding UTF8 (Join-Path $golden 'state.json')
"""
        )
    return (
        preamble
        + r"""if(!(Test-Path -LiteralPath (Join-Path $golden 'sealed'))){throw 'windows_golden_unsealed: capture and register a sealed golden before reset'}
$state=Get-Content -Raw (Join-Path $golden 'state.json') | ConvertFrom-Json
$source=Join-Path $golden 'profile'; $target=$profileRoot
"""
        + copy
        + r"""[Environment]::SetEnvironmentVariable('Path',$state.user_path,'User')
$env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+$state.user_path
$owned=@(Get-ScheduledTask | Where-Object {$_.Principal.UserId -in @($env:USERNAME,[Security.Principal.WindowsIdentity]::GetCurrent().Name)})
foreach($task in $owned){
 if(!($state.tasks | Where-Object {$_.name -eq $task.TaskName -and $_.path -eq $task.TaskPath})){
  Stop-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath
  Unregister-ScheduledTask -TaskName $task.TaskName -TaskPath $task.TaskPath -Confirm:$false
 }
}
foreach($task in $state.tasks){Register-ScheduledTask -TaskName $task.name -TaskPath $task.path -Xml $task.xml -Force | Out-Null}
if([Environment]::GetEnvironmentVariable('Path','User') -cne $state.user_path){throw 'windows_path_restore_failed: repair user environment access and reset again'}
"""
    )


def profile_operation(control, operation, path):
    try:
        script = profile_script(control, operation, path)
        result = control._run(script, timeout=600)
    except ValueError as exc:
        return HostActionResult(
            False, {"recovery": str(exc)}, "windows_golden_path_unsafe"
        )
    ok = result.returncode == 0
    return HostActionResult(
        ok,
        {
            "operation": operation,
            "golden_baseline_path": path,
            "profile": control.home,
            "preserved_identity_paths": list(PRESERVED_DIRECTORIES),
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


def reach_baseline(control, name):
    if name not in {"fresh-host", "shell-preconfigured"}:
        raise ValueError("unknown native Windows baseline " + name)
    restored = control.reset_installer_test_host()
    if not restored.ok or name == "fresh-host":
        return restored
    from yoke_cli.config import distribution, machine_config

    origin = distribution.origin_for_connection(machine_config.active_connection())
    script = (
        "$env:YOKE_INSTALL_YES='1'; $env:YOKE_NO_SETUP='1'; "
        f"$env:YOKE_INSTALL_BASE_URL={quote(origin)}; "
        f"$installer=Invoke-WebRequest -UseBasicParsing {quote(origin + '/install.ps1')}; "
        "& ([ScriptBlock]::Create($installer.Content)) --yes --no-setup; "
        "if($LASTEXITCODE){exit $LASTEXITCODE}"
    )
    installed = control._run(script, timeout=1200)
    if installed.returncode:
        return HostActionResult(
            False, {"recovery": installed.stderr}, "windows_baseline_install_failed"
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
            "path_state": paths,
            "launcher": control.path_state.yoke_bin,
        },
        None if ok else "windows_baseline_verification_failed",
    )
