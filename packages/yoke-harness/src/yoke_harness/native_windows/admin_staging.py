"""Stage administrator scripts through SFTP, independently verifying their bytes."""

import hashlib
from pathlib import Path
import subprocess
import tempfile
import time
from uuid import uuid4

from yoke_contracts.owner_private_path import (
    create_owner_private_directory, is_owner_private_file, write_owner_private,
)
from yoke_harness.native_windows.transport import encoded, quote


PREPARE = r"""$ErrorActionPreference='Stop'
$root=ROOT;$id=[Security.Principal.WindowsIdentity]::GetCurrent()
if(!([Security.Principal.WindowsPrincipal]::new($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator staging requires administrator'}
foreach($p in @('C:\','C:\ProgramData')){
 $f=Get-Item -LiteralPath $p -Force -ErrorAction Stop
 if(!$f.PSIsContainer -or ($f.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Staging ancestor invalid'}
}
if(Test-Path -LiteralPath $root){throw 'Staging collision; preserve existing path'}
New-Item -ItemType Directory -Path $root -ErrorAction Stop|Out-Null
$acl=[Security.AccessControl.DirectorySecurity]::new()
$acl.SetOwner($id.User);$acl.SetAccessRuleProtection($true,$false)
foreach($sid in @('S-1-5-18','S-1-5-32-544')){
 $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
}
Set-Acl -LiteralPath $root -AclObject $acl -ErrorAction Stop
CHECK_DIRECTORY
Write-Output 'YOKE_ADMIN_STAGE_OWNED'
"""

CHECK_DIRECTORY = r"""
$dir=Get-Item -LiteralPath $root -Force -ErrorAction Stop
$acl=Get-Acl -LiteralPath $root -ErrorAction Stop
$rules=@($acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
if(!$dir.PSIsContainer -or ($dir.Attributes -band [IO.FileAttributes]::ReparsePoint) -or !$acl.AreAccessRulesProtected -or $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne [Security.Principal.WindowsIdentity]::GetCurrent().User.Value -or $rules.Count -ne 2){throw 'Private staging directory changed; preserve'}
foreach($r in $rules){
 if($r.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544') -or $r.AccessControlType -ne 'Allow' -or $r.FileSystemRights -ne 'FullControl'){throw 'Private staging ACL changed; preserve'}
}
"""

CHECK_FILE_ACCESS = r"""
$fileAcl=Get-Acl -LiteralPath $p -ErrorAction Stop
$fileRules=@($fileAcl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
if(!$fileRules.Count){throw 'Staged file access unverified; preserve'}
foreach($r in $fileRules){
 if($r.AccessControlType -ne 'Allow' -or $r.IdentityReference.Value -notin @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value,'S-1-5-18','S-1-5-32-544')){throw 'Staged file access is not private; preserve'}
}
"""


def command(script):
    return "powershell.exe -NoProfile -NonInteractive -EncodedCommand " + encoded(script)


def stage_script(ssh, payload, root, diagnostics, *, deadline):
    """One staging deadline; no script or optional secret input is put in argv."""
    local = create_owner_private_directory(
        Path(tempfile.gettempdir()) / ("yoke-admin-" + uuid4().hex)
    )
    source = local / "script.ps1"
    failure = None

    def run(phase, argv, **kwargs):
        before = time.monotonic()
        remaining = deadline - before
        event = {"phase": phase, "remaining_seconds": round(max(0, remaining), 3)}
        diagnostics["steps"].append(event)
        try:
            if remaining <= 0:
                raise subprocess.TimeoutExpired("Windows administrator staging", 90)
            result = subprocess.run(
                argv, capture_output=True, text=True, timeout=remaining, **kwargs,
            )
            event["exit_code"] = result.returncode
            if result.returncode:
                error = RuntimeError("windows_admin_staging_" + phase + "_failed")
                error.staging_result = result
                raise error
            event["outcome"] = "completed"
            return result
        except BaseException as exc:
            event["outcome"] = type(exc).__name__
            raise
        finally:
            event["duration_seconds"] = round(time.monotonic() - before, 3)

    try:
        write_owner_private(source, payload)
        if not is_owner_private_file(source):
            raise RuntimeError("windows_admin_local_staging_not_private")
        target = root + r"\script.ps1"
        # SFTP batch quoting is not shell quoting. Refuse unsafe literal paths.
        if any(c in str(source) + target for c in '\r\n\0*?[]"'):
            raise RuntimeError("windows_admin_sftp_path_invalid")
        prepare = PREPARE.replace("ROOT", quote(root)).replace(
            "CHECK_DIRECTORY", CHECK_DIRECTORY,
        )
        prepared = run("prepare", [*ssh, command(prepare)])
        if "YOKE_ADMIN_STAGE_OWNED" not in prepared.stdout.splitlines():
            raise RuntimeError("windows_admin_staging_ownership_unverified")
        diagnostics["remote_directory_owned"] = True
        batch = 'put "' + str(source).replace("\\", "/") + '" "/' + target.replace("\\", "/") + '"\n'
        run("sftp", ["sftp", *ssh[1:-1], "-b", "-", ssh[-1]], input=batch)
        digest = hashlib.sha256(payload).hexdigest()
        verify = (
            "$ErrorActionPreference='Stop';$root=" + quote(root) + ";"
            + CHECK_DIRECTORY
            + "$p=Join-Path $root 'script.ps1';$f=Get-Item -LiteralPath $p -Force -ErrorAction Stop\n"
            + f"if($f.PSIsContainer -or ($f.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $f.Length -ne {len(payload)} -or (Get-FileHash -LiteralPath $p -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -ne '{digest}'){{throw 'Staged script differs; preserve'}}\n"
            + "if((Get-Acl -LiteralPath $p).GetOwner([Security.Principal.SecurityIdentifier]).Value -notin @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value,'S-1-5-32-544')){throw 'Staged script owner differs; preserve'}\n"
            + CHECK_FILE_ACCESS
            + "Write-Output 'YOKE_ADMIN_SCRIPT_VERIFIED'"
        )
        verified = run("verify", [*ssh, command(verify)])
        if "YOKE_ADMIN_SCRIPT_VERIFIED" not in verified.stdout.splitlines():
            raise RuntimeError("windows_admin_staging_hash_unverified")
        diagnostics["last_verified_offset"] = len(payload)
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            source.unlink(missing_ok=True)
            local.rmdir()
            diagnostics["local_cleanup"] = "verified_absent"
        except OSError as exc:
            diagnostics["local_cleanup"] = "unverified"
            if failure is None:
                raise RuntimeError("windows_admin_local_cleanup_failed") from exc
            failure.local_cleanup_cause = exc


def cleanup_script(root, *, owned, payload):
    """Remove only the known script and an empty, verified owned directory."""
    prefix = "$ErrorActionPreference='Stop';$root=" + quote(root) + ";\n"
    if not owned:
        return prefix + "if(Test-Path -LiteralPath $root){throw 'Staging ownership unverified; preserve'}"
    checks = (
        f"if($f.Length -ne {len(payload)} -or (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() -ne '{hashlib.sha256(payload).hexdigest()}'){{throw 'Staging bytes differ; preserve'}}\n"
        + "if((Get-Acl -LiteralPath $p).GetOwner([Security.Principal.SecurityIdentifier]).Value -notin @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value,'S-1-5-32-544')){throw 'Staging owner differs; preserve'}"
        + CHECK_FILE_ACCESS
    )
    return prefix + r"""
if(Test-Path -LiteralPath $root){
CHECK_DIRECTORY
 if(@(Get-CimInstance Win32_Process -ErrorAction Stop|Where-Object {$_.ProcessId -ne $PID -and ([string]$_.CommandLine).Contains($root)}).Count){throw 'Staging referenced by process; preserve'}
 if(@(Get-ChildItem -LiteralPath $root -Force -ErrorAction Stop|Where-Object Name -ne 'script.ps1').Count){throw 'Staging has unexpected files; preserve'}
 $p=Join-Path $root 'script.ps1'
 if(Test-Path -LiteralPath $p){
  $f=Get-Item -LiteralPath $p -Force -ErrorAction Stop
  if($f.PSIsContainer -or ($f.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Staged file identity changed; preserve'}
CHECK_FILE
  Remove-Item -LiteralPath $p -Force -ErrorAction Stop
 }
 if(@(Get-ChildItem -LiteralPath $root -Force -ErrorAction Stop).Count){throw 'Staging has unexpected files; preserve'}
 Remove-Item -LiteralPath $root -Force -ErrorAction Stop
}
if(Test-Path -LiteralPath $root){throw 'Owned staging cleanup failed'}
""".replace("CHECK_DIRECTORY", CHECK_DIRECTORY).replace("CHECK_FILE", checks)
