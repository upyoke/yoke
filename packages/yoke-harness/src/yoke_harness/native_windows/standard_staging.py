"""Verified SFTP payloads under the resolved standard Windows user's home."""

from contextlib import contextmanager
import hashlib
from types import SimpleNamespace
import time
from uuid import uuid4

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.native_windows import admin_staging
from yoke_harness.native_windows.powershell import quote
from yoke_harness.ssh_test_machine_transport import SshTestMachineTransport


ANCESTORS = r"""
$id=[Security.Principal.WindowsIdentity]::GetCurrent()
if(([Security.Principal.WindowsPrincipal]::new($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Standard staging requires standard user'}
$stageHome=HOME
if($env:USERPROFILE -ne $stageHome -or (Split-Path -Parent $root) -ne $stageHome){throw 'Staging home differs from resolved user profile'}
$ancestor=$stageHome
while($ancestor){
 $f=Get-Item -LiteralPath $ancestor -Force -ErrorAction Stop
 if(!$f.PSIsContainer -or ($f.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Staging ancestor invalid'}
 $ancestor=Split-Path -Parent $ancestor
}
"""


def standard_policy(home):
    ancestors = ANCESTORS.replace("HOME", quote(home))
    # Three exact protected grants: this user, SYSTEM and Administrators.
    directory = ancestors + r"""
$d=Get-Item -LiteralPath $root -Force -ErrorAction Stop
$a=Get-Acl -LiteralPath $root -ErrorAction Stop
$rs=@($a.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
if(!$d.PSIsContainer -or ($d.Attributes -band [IO.FileAttributes]::ReparsePoint) -or !$a.AreAccessRulesProtected -or $a.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $id.User.Value -or $rs.Count -ne 3){throw 'Stage identity changed'}
foreach($r in $rs){if($r.IdentityReference.Value -notin @($id.User.Value,'S-1-5-18','S-1-5-32-544') -or $r.AccessControlType -ne 'Allow' -or $r.FileSystemRights -ne 'FullControl'){throw 'Stage ACL changed'}}
"""
    prepare = r"""$ErrorActionPreference='Stop';$root=ROOT
ANCESTORS
if(Test-Path -LiteralPath $root){throw 'Staging collision; preserve existing path'}
New-Item -ItemType Directory -Path $root -ErrorAction Stop|Out-Null
$acl=[Security.AccessControl.DirectorySecurity]::new()
$acl.SetOwner($id.User);$acl.SetAccessRuleProtection($true,$false)
foreach($sid in @($id.User.Value,'S-1-5-18','S-1-5-32-544')){
 $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'FullControl','ContainerInherit,ObjectInherit','None','Allow'))
}
Set-Acl -LiteralPath $root -AclObject $acl -ErrorAction Stop
CHECK_DIRECTORY
Write-Output 'YOKE_ADMIN_STAGE_OWNED'
""".replace("ANCESTORS", ancestors)
    return {
        "prepare": prepare, "directory": directory,
        "owner": "if((Get-Acl -LiteralPath $p).GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $id.User.Value){throw 'Standard staging owner differs; preserve'}\n",
        "file_access": r"""
$fa=Get-Acl -LiteralPath $p -ErrorAction Stop
$fr=@($fa.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]))
if(!$fr.Count -or @($fr|Where-Object {$_.AccessControlType -ne 'Allow' -or $_.IdentityReference.Value -notin @($id.User.Value,'S-1-5-18','S-1-5-32-544')}).Count){throw 'Stage file ACL changed'}
""",
        # Standard users cannot enumerate Win32_Process through CIM. The caller
        # must preserve staging whenever command completion is ambiguous.
        "process": "",
    }


@contextmanager
def verified_payload(control, payload):
    root = control.home + "\\.yoke-stage-" + uuid4().hex
    policy = standard_policy(control.home)
    diagnostics = {
        "path": root, "total_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "steps": [], "remote_directory_owned": False, "last_verified_offset": 0,
    }
    stage = SimpleNamespace(
        path=quote(root + r"\script.ps1"), diagnostics=diagnostics,
        execution_pending=False, primary_result=None,
    )
    # Refuse an unsupported home length before creating any remote directory.
    prepare = policy["prepare"].replace("ROOT", quote(root)).replace("CHECK_DIRECTORY", policy["directory"])
    admin_staging.command(prepare)
    control._ssh_argv(admin_staging.cleanup_script(root, owned=True, payload=payload, policy=policy))
    # Use the base connection prefix, never parse a PowerShell command as argv.
    ssh = SshTestMachineTransport._ssh_argv(control, "")[:-1]
    failure = None
    try:
        admin_staging.stage_script(
            ssh, payload, root, diagnostics, deadline=time.monotonic() + 90,
            policy=policy,
        )
        yield stage
    except BaseException as exc:
        failure = exc
        exc.staging_diagnostics = diagnostics
        raise
    finally:
        if stage.execution_pending:
            diagnostics["cleanup"] = "preserved_ambiguous_execution"
        else:
            try:
                script = admin_staging.cleanup_script(
                    root, owned=diagnostics["remote_directory_owned"],
                    payload=payload, policy=policy,
                )
                # Cleanup is small and encoded; bypass staging recursion.
                cleaned = SshTestMachineTransport._run(control, script, timeout=30)
                diagnostics["cleanup"] = "verified_absent" if cleaned.returncode == 0 else "unverified"
                if cleaned.returncode:
                    error = HostControlLocalError(
                        code="native_windows_staging_cleanup_failed", phase="script_cleanup",
                        detail="Verified Windows staging cleanup failed; preserve the named path.",
                        recovery_hint="Inspect the private staging diagnostics and exact owned bytes before recovery.",
                        exit_code=cleaned.returncode, stdout=cleaned.stdout, stderr=cleaned.stderr,
                        secrets=getattr(control, "secret_values", ()),
                    )
                    error.cleanup_result = cleaned
                    raise error
            except BaseException as exc:
                diagnostics["cleanup"] = "unverified"
                if failure is not None:
                    failure.staging_cleanup_cause = exc
                else:
                    exc.staging_diagnostics = diagnostics
                    if stage.primary_result is not None:
                        exc.primary_result = stage.primary_result
                    raise
