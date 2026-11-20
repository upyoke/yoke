"""Lease-bound recovery through one provisioned, fixed administrator task."""

import json
import time
from uuid import uuid4

from yoke_contracts.designed_wait import announce_designed_wait
from yoke_contracts.machine_qa_failures import HostControlLocalError

from yoke_harness.native_windows.journal_inventory import INVENTORY
from yoke_harness.native_windows.journal_rebaseline import REBASELINE
from yoke_harness.native_windows.tasks import require_task_result, start_fixed_task
from yoke_harness.native_windows.receipts import RECEIPT, PUBLISH

ROOT = r"C:\ProgramData\YokeQa"
TASK = "YokeQaMachineSettings"

# Provision this fixed program as Administrator. The test user can request
# capture/restore, but cannot replace the administrator program or its journal.
PROGRAM = r"""
param([switch]$InspectTools,[string]$AcceptToolsFingerprint='',[string]$ApprovalReason='')
$ErrorActionPreference='Stop'
$root='C:\ProgramData\YokeQa'
$journal="$root\private\journal.json"
$receipt='RECEIPT_PATH'
RECEIPT_PUBLISH
JOURNAL_INVENTORY
JOURNAL_REBASELINE
function Machine-Packages {
 # Correlate both HKLM uninstall views with the installed Programs/MSI packages.
 # The test user's tools belong to the profile golden.
 $machine=@(Get-ItemProperty -Path @(
  'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
 ) -ErrorAction SilentlyContinue)
 @(Get-Package -ProviderName Programs,msi -ErrorAction SilentlyContinue |
   Where-Object {
    $name=$_.Name; $version=$_.Version
    $machine | Where-Object {$_.DisplayName -eq $name -and $_.DisplayVersion -eq $version} | Select-Object -First 1
   })
}
function Tools {
 @(Machine-Packages | Select-Object Name,Version,ProviderName | Sort-Object Name,Version,ProviderName)
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
function State-Difference($state,$actual) {
 $diff=[ordered]@{}
 if((Json-Key $state.policy) -cne (Json-Key $actual.policy)){
  $policy=Difference @(Policy-Entries $state.policy) @(Policy-Entries $actual.policy) ${function:Json-Key}
  if(!(Has-Difference $policy)){
   $policy=Difference @([pscustomobject]@{sha256=(Text-Hash $state.policy)}) @([pscustomobject]@{sha256=(Text-Hash $actual.policy)}) ${function:Json-Key}
  }
  $diff.policy=$policy
 }
 foreach($field in @('long_paths','certificates')){
  $delta=Difference @($state.$field) @($actual.$field) ${function:Json-Key}
  if(Has-Difference $delta){$diff[$field]=$delta}
 }
 $tools=Difference @($state.tools) @($actual.tools) ${function:Tool-Key}
 if(Has-Difference $tools){$diff.tools=$tools}
 $diff
}
$attempts=[Collections.Generic.List[object]]::new()
$diff=[ordered]@{}
$state=$null
$request=$null
$lock=$null
try {
 $adminMode=$InspectTools -or $AcceptToolsFingerprint -or $ApprovalReason
 if($adminMode){
  # Direct elevated invocation only. No action or argument comes from the shared request.
  Assert-YokeRecoveryObject (Split-Path -Parent $journal) $true
 }else{
  $request=Get-Content -Raw "$root\requests\request.json" | ConvertFrom-Json
 }
 try {$lock=[IO.File]::Open("$root\private\journal.lock",'OpenOrCreate','ReadWrite','None')}
 catch {throw 'windows_journal_lock_unavailable: finish the active recovery or repair the private journal lock and retry'}
 if($adminMode){Update-ToolBaseline;return}
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
  Restore-Tools @($state.tools) @(Tools) $attempts
  $diff=State-Difference $state (State)
  if($attempts.status -contains 'ineffective'){
   throw 'windows_tool_uninstall_ineffective: the package remains installed; inspect attempts and repair it as Administrator'
  }
  if($diff.Count){
   throw 'windows_journal_restore_unverified: machine settings still differ; inspect the inventory and repair as Administrator'
  }
  Remove-Item -LiteralPath $journal
 }
 $result=@{token=$request.token;ok=$true;action=$request.action;lease=$request.lease}
 if($request.action -eq 'restore'){
  # Read-only proof under the existing SYSTEM action; standard SSH cannot
  # query this provider. Neither new actions nor test-user privileges are added.
  $result.features=@(Get-CimInstance Win32_OptionalFeature -Filter "Name='Microsoft-Windows-Subsystem-Linux' OR Name='VirtualMachinePlatform'" |
   Select-Object Name,InstallState)
 }
 Publish-YokeReceipt $result
} catch {
 if($adminMode -or !$request){throw}
 $reason=$_.Exception.Message
 if($reason -notmatch '^windows_[a-z_]+:'){
  $reason='windows_journal_operation_failed: inspect the protected task and repair the named journal action as Administrator'
 }
 if($state -and $request.action -eq 'restore'){
  if(!$diff.Count){
   try {$diff=State-Difference $state (State)}catch{
    $reason+='; the current machine inventory could not be read'
   }
  }
  @{lease=$request.lease;saved_lease=$saved.lease;reason=$reason;differences=$diff;attempts=@($attempts.ToArray())} |
   ConvertTo-Json -Depth 10 | Set-Content -LiteralPath "$root\private\last-restore-diff.json" -Encoding UTF8
 }
 $safeAttempts=@($attempts | Select-Object -First 12 | ForEach-Object {
  @{action=$_.action;tool=(Public-Row $_.tool);status=$_.status;exit_code=$_.exit_code}
 })
 Publish-YokeReceipt @{token=$request.token;ok=$false;action=$request.action;lease=$request.lease;reason=$reason;
   differences=(Public-Diff $diff);attempts=$safeAttempts;attempt_count=$attempts.Count;
   recovery='Inspect the differing rows and attempts. Repair the settings or approve verified tool drift as Administrator, then retry the serial lease.'}
 exit 1
} finally {
 if($lock){$lock.Dispose()}
}
"""
PROGRAM = (
    PROGRAM.replace("RECEIPT_PATH", RECEIPT)
    .replace("RECEIPT_PUBLISH", PUBLISH)
    .replace("JOURNAL_INVENTORY", INVENTORY)
    .replace("JOURNAL_REBASELINE", REBASELINE)
)



def _receipt_diagnostics(receipt):
    differences = receipt.get("differences")
    if isinstance(differences, dict):
        for field in ("tools", "policy", "long_paths", "certificates"):
            diff = differences.get(field)
            if not isinstance(diff, dict):
                continue
            for side in ("saved_only", "current_only"):
                rows = diff.get(side)
                if not isinstance(rows, list):
                    continue
                for row in rows[:6]:
                    if isinstance(row, dict):
                        yield f"{field}.{side}: {json.dumps(row, ensure_ascii=False)}"
                count = diff.get(f"{side}_count")
                if type(count) is int and count > min(len(rows), 6):
                    yield f"{field}.{side}: {count} total; see the private last-restore-diff.json for all rows"
    attempts = receipt.get("attempts")
    if isinstance(attempts, list):
        for attempt in attempts[:12]:
            if isinstance(attempt, dict):
                yield f"tool attempt: {json.dumps(attempt, ensure_ascii=False)}"
        count = receipt.get("attempt_count")
        if type(count) is int and count > min(len(attempts), 12):
            yield f"tool attempts: {count} total; see the private last-restore-diff.json for all attempts"


def journal_operation(control, action):
    lease = getattr(control, "qa_lease_id", None)
    if lease is None:
        raise RuntimeError(
            "windows_journal_lease_required: acquire the machine QA lease before changing machine settings"
        )
    token = uuid4().hex
    control.upload_remote_text(
        ROOT + r"\requests\request.json",
        json.dumps(
            {
                "action": action,
                "lease": str(lease),
                "token": token,
            }
        ),
    )
    started = control._run(start_fixed_task(TASK))
    require_task_result(control, started, phase="journal_task_start")
    announce_designed_wait(
        "native Windows machine settings " + action, max_wait_seconds=300
    )
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        value = control.read_remote_text(RECEIPT)
        if value:
            try:
                receipt = json.loads(value.lstrip("\ufeff"))
            except ValueError:
                raise HostControlLocalError(
                    code="native_windows_journal_receipt_invalid", phase="journal_receipt",
                    detail="The fixed recovery task returned malformed JSON.",
                    recovery_hint="Preserve the journal, repair the fixed recovery program and retry the serial lease.",
                ) from None
            if not isinstance(receipt, dict) or not isinstance(receipt.get("token"), str):
                raise HostControlLocalError(
                    code="native_windows_journal_receipt_invalid", phase="journal_receipt",
                    detail="The fixed recovery task returned an invalid receipt schema.",
                    recovery_hint="Preserve the journal, repair the fixed recovery program and retry the serial lease.",
                )
            if receipt["token"] == token:
                if receipt.get("lease") != str(lease) or receipt.get("action") != action or type(receipt.get("ok")) is not bool:
                    raise HostControlLocalError(
                        code="native_windows_journal_receipt_invalid", phase="journal_receipt",
                        detail="The machine recovery receipt does not match its current lease and action.",
                        recovery_hint="Preserve the journal, inspect the fixed recovery task and acquire a fresh serial QA lease before retrying.",
                    )
                if receipt["ok"] is False:
                    raise HostControlLocalError(
                        code="native_windows_journal_failed", phase="journal_" + action,
                        detail=str(receipt.get("reason")),
                        recovery_hint=str(receipt.get("recovery")),
                        secrets=getattr(control, "secret_values", ()),
                        diagnostics=tuple(_receipt_diagnostics(receipt)),
                    )
                return receipt
        time.sleep(0.2)
    raise RuntimeError(
        "windows_journal_timeout: inspect the fixed recovery task and its durable journal; restore before releasing or reusing the machine"
    )
