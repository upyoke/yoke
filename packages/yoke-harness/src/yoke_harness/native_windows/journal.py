"""Lease-bound recovery through one provisioned, fixed administrator task."""

import json
import time
from uuid import uuid4

from yoke_contracts.designed_wait import announce_designed_wait
from yoke_contracts.machine_qa_failures import HostControlLocalError

from yoke_harness.native_windows.transport import quote

ROOT = r"C:\ProgramData\YokeQa"
TASK = "YokeQaMachineSettings"

# Provision this fixed program as Administrator. The test user can request
# capture/restore, but cannot replace the administrator program or its journal.
PROGRAM = r"""
$ErrorActionPreference='Stop'
$root='C:\ProgramData\YokeQa'
$request=Get-Content -Raw "$root\requests\request.json" | ConvertFrom-Json
$journal="$root\private\journal.json"
$receipt="$root\requests\receipt.json"
function Tools {
 @(Get-Package -ProviderName Programs,msi -ErrorAction SilentlyContinue |
   Select-Object Name,Version,ProviderName | Sort-Object Name,Version,ProviderName)
}
function Certificates {
 @(Get-ChildItem Cert:\LocalMachine -Recurse | Where-Object Thumbprint |
   ForEach-Object { [pscustomobject][ordered]@{path=('Cert:\'+$_.PSParentPath.Replace('Microsoft.PowerShell.Security\Certificate::',''));thumbprint=$_.Thumbprint} } |
   Sort-Object path,thumbprint)
}
function LongPaths {
 $key='HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem'
 $value=Get-ItemProperty -LiteralPath $key -Name LongPathsEnabled -ErrorAction SilentlyContinue
 [pscustomobject][ordered]@{exists=($null -ne $value);value=$value.LongPathsEnabled}
}
function State {
 @{policy=(Get-AppLockerPolicy -Local -Xml);long_paths=(LongPaths);certificates=@(Certificates);tools=@(Tools)}
}
function Same($a,$b) { (ConvertTo-Json -InputObject $a -Depth 20 -Compress) -ceq (ConvertTo-Json -InputObject $b -Depth 20 -Compress) }
try {
 if($request.action -notin @('capture','restore')){throw 'windows_journal_action_invalid: use capture or restore'}
 if($request.lease -notmatch '^[A-Za-z0-9-]+$'){throw 'windows_journal_lease_invalid: acquire a QA lease'}
 if($request.action -eq 'capture'){
  if(Test-Path $journal){throw 'windows_journal_recovery_owed: restore the interrupted lease before another capture'}
  $state=State
  # Export public machine certificates for restoring removed trust roots.
  New-Item -ItemType Directory -Force "$root\private\certificates" | Out-Null
  foreach($cert in $state.certificates){
   Export-Certificate -Cert (Get-Item ($cert.path+'\'+$cert.thumbprint)) -FilePath ("$root\private\certificates\"+$cert.thumbprint+'.cer') -Force | Out-Null
  }
  @{lease=$request.lease;state=$state} | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 "$journal.tmp"
  Move-Item "$journal.tmp" $journal
 } elseif(Test-Path $journal) {
  $saved=Get-Content -Raw $journal | ConvertFrom-Json
  $state=$saved.state
  # The saved owner is retained through recovery, even when its controller died.
  $state.policy | Set-Content -Encoding UTF8 "$root\private\policy.xml"
  Set-AppLockerPolicy -XmlPolicy "$root\private\policy.xml"
  $key='HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem'
  if($state.long_paths.exists){Set-ItemProperty -LiteralPath $key -Name LongPathsEnabled -Value $state.long_paths.value}
  else{Remove-ItemProperty -LiteralPath $key -Name LongPathsEnabled -ErrorAction SilentlyContinue}
  foreach($cert in (Certificates)){
   if(!($state.certificates | Where-Object {$_.path -eq $cert.path -and $_.thumbprint -eq $cert.thumbprint})){
    Remove-Item -LiteralPath ($cert.path+'\'+$cert.thumbprint)
   }
  }
  foreach($cert in $state.certificates){
   if(!(Test-Path -LiteralPath ($cert.path+'\'+$cert.thumbprint))){
    Import-Certificate -FilePath ("$root\private\certificates\"+$cert.thumbprint+'.cer') -CertStoreLocation $cert.path | Out-Null
   }
  }
  foreach($tool in (Tools)){
   if(!($state.tools | Where-Object {$_.Name -eq $tool.Name -and $_.Version -eq $tool.Version})){
    Get-Package -Name $tool.Name -RequiredVersion $tool.Version -ProviderName $tool.ProviderName | Uninstall-Package -Force | Out-Null
   }
  }
  # Provision an owner-only installer cache for tools a policy case may remove.
  foreach($tool in $state.tools){
   if(!((Tools) | Where-Object {$_.Name -eq $tool.Name -and $_.Version -eq $tool.Version})){
    $catalog=Get-Content -Raw "$root\private\tool-installers.json" | ConvertFrom-Json
    $installer=$catalog | Where-Object {$_.name -eq $tool.Name -and $_.version -eq $tool.Version} | Select-Object -First 1
    if(!$installer -or (Get-FileHash -LiteralPath $installer.path).Hash -ne $installer.sha256){throw 'windows_tool_restore_unavailable: provision a hash-verified cached installer for the removed tool and retry restore'}
    $process=Start-Process -FilePath $installer.path -ArgumentList $installer.arguments -Wait -PassThru
    if($process.ExitCode -notin @(0,3010)){throw 'windows_tool_restore_failed: repair the cached installer and retry restore'}
   }
  }
  $actual=State
  foreach($field in @('policy','long_paths','certificates','tools')){
   if(!(Same $state.$field $actual.$field)){throw "windows_journal_restore_unverified: $field differs; repair it as administrator and retry restore"}
  }
  Remove-Item -LiteralPath $journal
 }
 @{token=$request.token;ok=$true;action=$request.action;lease=$request.lease} | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 $receipt
} catch {
 @{token=$request.token;ok=$false;action=$request.action;lease=$request.lease;reason="$_";
   recovery='Restore the saved machine settings as administrator and rerun the fixed recovery task before releasing or reusing the machine.'} |
   ConvertTo-Json -Compress | Set-Content -Encoding UTF8 $receipt
 exit 1
}
"""


_RESTORE_RECOVERY = (
    "Inspect the fixed YokeQaMachineSettings task and its durable journal. "
    "Restore the saved settings as administrator before reusing the machine."
)


def _journal_failure(control, action, code, detail, **evidence):
    return HostControlLocalError(
        code=code,
        phase=f"windows_machine_settings_{action}",
        detail=detail,
        recovery_hint=evidence.pop("recovery_hint", _RESTORE_RECOVERY),
        secrets=getattr(control, "secret_values", ()),
        **evidence,
    )


def journal_operation(control, action):
    lease = getattr(control, "qa_lease_id", None)
    if lease is None:
        raise _journal_failure(
            control, action, "windows_journal_lease_required",
            "Changing native Windows machine settings requires a QA lease.",
            recovery_hint="Acquire a machine QA lease before changing machine settings.",
        )
    token = uuid4().hex
    try:
        control.upload_remote_text(
            ROOT + r"\requests\request.json",
            json.dumps({"action": action, "lease": str(lease), "token": token}),
        )
        started = control._run(f"Start-ScheduledTask -TaskName {quote(TASK)}")
    except HostControlLocalError:
        raise
    except (OSError, RuntimeError) as exc:
        raise _journal_failure(
            control, action, "windows_journal_request_failed",
            "Could not submit the native Windows machine settings request.",
            stderr=str(exc),
        ) from exc
    if started.returncode:
        raise _journal_failure(
            control, action, "windows_journal_task_unavailable",
            "Could not start the native Windows machine settings task.",
            recovery_hint="Provision the fixed administrator recovery task and grant the test user start access.",
            exit_code=started.returncode, stderr=started.stderr,
        )
    announce_designed_wait(
        "native Windows machine settings " + action, max_wait_seconds=300
    )
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            value = control.read_remote_text(ROOT + r"\requests\receipt.json")
            receipt = json.loads(value.lstrip("\ufeff")) if value else {}
            if not isinstance(receipt, dict):
                raise ValueError("journal receipt must be a JSON object")
        except HostControlLocalError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise _journal_failure(
                control, action, "windows_journal_receipt_unreadable",
                "Could not read a valid native Windows machine settings receipt.",
                stderr=str(exc),
            ) from exc
        if receipt.get("token") == token:
            if not receipt.get("ok"):
                raise _journal_failure(
                    control, action, "windows_journal_operation_failed",
                    "The native Windows machine settings task refused the request.",
                    stderr=str(receipt.get("reason") or ""),
                )
            return receipt
        time.sleep(0.2)
    raise _journal_failure(
        control, action, "windows_journal_timeout",
        "The native Windows machine settings task produced no matching receipt within 300 seconds.",
    )
