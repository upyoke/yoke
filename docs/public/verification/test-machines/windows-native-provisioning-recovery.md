# Native Windows provisioning recovery

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Native Windows provisioning recovery
<!-- /yoke:breadcrumbs -->

Return to [native Windows setup](windows-native-host-provisioning.md) for
Azure identity, normal provisioning, registration and the remaining QA steps.
Keep every failed-window receipt and verified power state with the inventory.

## Bounded recovery when administrator SSH is unavailable

Within approved authority, cap each start at twenty minutes, reserve cleanup
at minute seventeen and verify `PowerState/deallocated` by minute twenty.
Stop on ambiguity; never infer retry/process-kill permission from timeout.
If installed/running OpenSSH has blocked TCP22, inspect managed `YokeQaSsh`:
`New-NetFirewallRule` needs `-DisplayName` even with `-Name`, otherwise it can
prompt noninteractively. Save this nonsecret script as `ssh-firewall.ps1`:

```powershell
$ErrorActionPreference='Stop'
Get-NetFirewallRule -Name YokeQaSsh -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -Name YokeQaSsh -DisplayName 'Yoke QA SSH' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22 -Profile Any -RemoteAddress Any -ErrorAction Stop | Out-Null
$r=Get-NetFirewallRule -PolicyStore ActiveStore -Name YokeQaSsh -ErrorAction Stop
$p=$r | Get-NetFirewallPortFilter -ErrorAction Stop
if($r.Enabled -ne 'True' -or $r.Direction -ne 'Inbound' -or $r.Action -ne 'Allow' -or $p.LocalPort -ne '22'){throw 'effective SSH rule invalid'}
Restart-Service sshd -ErrorAction Stop
'YOKE_SSH_FIREWALL_READY'
```

Run **one managed Run Command v2**, retaining its named resource for audit:

```text
az vm run-command create --resource-group GROUP --vm-name VM --name yoke-native-ssh-recovery --script @ssh-firewall.ps1 --timeout-in-seconds 120
az vm run-command show --resource-group GROUP --vm-name VM --name yoke-native-ssh-recovery --expand instanceView --query instanceView -o json
```

Require terminal success, exit code zero and `YOKE_SSH_FIREWALL_READY`;
ARM `Creating`/`Canceled` is not the guest result. Do not repeat removal or
create another guest invocation because the controller result is ambiguous.
Verify external TCP22, then key-only administrator SSH before continuing.
From a PowerShell controller (`KEY`, `ADMIN` and `HOST` are inventory values):

```powershell
if(!(Test-NetConnection HOST -Port 22 -InformationLevel Quiet)){throw 'TCP22 unreachable'}
$probe=@'
$ErrorActionPreference='Stop'
$id=[Security.Principal.WindowsIdentity]::GetCurrent()
$expected=Get-LocalUser -Name 'ADMIN' -ErrorAction Stop
if($id.User.Value -ne $expected.SID.Value -or !([Security.Principal.WindowsPrincipal]::new($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'wrong administrator token'}
$stale=@(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object {$_.CommandLine -match 'script0\.ps1'})
$stale | Select-Object ProcessId,CreationDate
if($stale.Count -ne 0){throw 'stale script0 process: report only, stop provisioning'}
'YOKE_ADMIN_AND_STALE_AUDIT_OK'
'@
$encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($probe))
ssh -i KEY -o BatchMode=yes ADMIN@HOST "powershell.exe -NoProfile -NonInteractive -EncodedCommand $encoded"
if($LASTEXITCODE -ne 0){throw 'administrator SSH audit failed'}
```

Never kill reported processes. Provision only after the zero-count audit;
retain all three receipts. Compare actual token SIDs to `Get-LocalUser`,
ADMIN alone has admin membership; inspect the test SID's registered path/hive.

## RDP firewall failure and partial setup

Windows Firewall rejects **both** `::1` and `127.0.0.1` as explicit loopback
address conditions. Do not replace the rejected IPv6 address with an IPv4 allow
rule. The provisioner removes legacy `YokeQaRdpLoopback`, disables stable
`RemoteDesktop-*` rules, requires all firewall profiles enabled/default inbound
block, and refuses RDP-capable allow rules. Package SID/family constraints exclude
packaged apps; `System` is a kernel listener, not TermService. Keep public3389 blocked;
forward explicitly with `ssh -i KEY -N -L 127.0.0.1:LOCAL_PORT:127.0.0.1:3389 USER@HOST`.
Require a real forwarded RDP negotiation and independently blocked direct RDP.

Earlier windows failed at the loopback rule (121 seconds) and writing the
partial key's empty DACL (124 seconds); each deallocated without registration.
After malformed-ACL CI recovery passed, the next run completed provisioning,
both SSH SID probes, profile/hive and blocked/forwarded RDP checks.
It registered **SETUP INCOMPLETE** and verified deallocation after 145 seconds;
tools, sign-ins, goldens and native QA remain unverified.
Preserve the partial account/profile and custody. Correct and run the **entire**
guest provisioner on disposable `windows-latest`, including actual SSH and RDP
forwarding, before requesting another VM window with exact-commit green evidence.
After successful setup register **SETUP INCOMPLETE**, immediately deallocate,
then run dispatched native QA separately. Failure means stop, deallocate, record
the exact guest error and inspect it; never mark registration or QA complete.

## Standard-user host-facts failure

A registered screenshot reached SSH as `winnative\yokeqa`, then reported
`native_windows_test_user_required`. The actual token was standard: both role
checks returned `false`. The failing read was `Get-CimInstance Win32_OperatingSystem`,
which returned `Access denied`; the old refusal hid that command failure.

The corrected probe reads `EditionID` and `CurrentBuildNumber` from
`HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion`, uses the built-in
Administrator enum, and requires an actual boolean privilege result. Execution
and malformed-output failures retain bounded, redacted subprocess evidence;
only a confirmed administrator token reports the standard-user refusal.
Do not add administrator membership or change WMI permissions to repair this.
Each diagnostic released its lease and deallocated the VM; it produced no
desktop PNG or native readiness pass. Verify the corrected probe and actual
desktop through the registered screenshot path before accepting readiness.

## Settings journal and interrupted-case recovery

SYSTEM task `YokeQaMachineSettings` accepts only capture/restore with a QA lease
identifier. Its program/journal in `C:\ProgramData\YokeQa\private` are writable
only by Administrators/SYSTEM; the standard user can start it and write
`C:\ProgramData\YokeQa\requests`, never replace the program. Before mutations
it records AppLocker policy, `LongPathsEnabled` presence/value, machine
certificate inventory and Programs/MSI tools; public certificates export privately.

Before baseline-tool removal, the administrator supplies its versioned installer
in the private recovery cache and `tool-installers.json`. Private-key certificate
removal requires a project-approved recovery procedure. Failed restore retains
the journal and reports its reason; it never becomes a passing case.

Cleanup restores policy, registry, certificates and tools and compares every
inventory. The next serial lease restores an interrupted journal before capture;
keep the machine unavailable until verified. Never use VM snapshots, delete the
journal, pass a policy failure or recapture a dirty machine.
