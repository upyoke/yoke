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
rule. The provisioner removes legacy `YokeQaRdpLoopback`, disables public-scoped
`RemoteDesktop-*` rules, requires all firewall profiles enabled/default inbound
block, and refuses RDP-capable allows without verified tailnet confinement.
Package SID/family constraints exclude packaged apps; `System` is a kernel
listener, not TermService. Keep public3389 blocked and permit direct tailnet RDP.
During bootstrap forward with `ssh -i KEY -N -L 127.0.0.1:LOCAL_PORT:127.0.0.1:3389 USER@HOST`.
Require real private RDP negotiation and independently blocked public RDP.

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

### Tailscale rule diagnosis and revised desktop policy

A later full refresh refused an RDP-capable GUID rule and deallocated after
179 seconds. That GUID was absent after reboot; the exact-name diagnostic
made no guest changes and deallocated after 177 seconds. A read-only capture
using the same classifier found two current `Tailscale-In` rules: any program,
service, protocol, port and remote address, confined to the VM's tailnet IPv4
and IPv6 local addresses. It had no lookup failures and deallocated after
183 seconds. GUIDs can change; retain the original failure and record current
filters rather than assuming a disappeared rule resolved the issue.

Operator decision request 15899 permits **direct RDP over the tailnet** and
forbids public RDP. No blanket 3389 block was applied; the source-only proposal
was withdrawn. Preserve the installed/joined Tailscale service and its rules.
Verify its running self addresses and live adapter assignments before accepting
address- or interface-confined RDP allows. Names alone, broad ranges, wildcard
interfaces or mixed public scope never authorize them. Prove tailnet RDP and
blocked public3389 before readiness; retain the SSH forward for bootstrap.

### Tailnet cutover and host replacement

Existing rollout: join first, deploy the no-rebind build, then settings-replace
`host` using the as-read token. Upgrade clients, then detach/delete the old
`20.124.243.250` under the recorded operator exception, using the detach/delete
commands in [the provisioning guide](windows-native-host-provisioning.md#tailscale-and-public-ip-lifetime).
An unmanaged IP attachment refuses with that recovery. A failed delete reports
`test_machine_power_stop_failed`: repair its named cause and retry verify/release.
Prove start/verify/stop keeps the host unchanged, with no QA_HOST or public IP left.

Before rebuilding, remove the old tailnet device, then join with the same name;
require no `-1` suffix. Verify the new SSH fingerprint, then clear the old pin
with `ssh-keygen -R VM_RESOURCE_ID -f KNOWN_HOSTS` in Yoke's Test Machine
known_hosts file. Re-read settings and use its token for any change; verify again.
For DNS/SSH failures check Tailscale, device expiry, controller DNS and sshd;
never change a live lease target to repair connectivity.

### Tailscale query context and preserved state

Windows CI exposed two API mismatches: query `RemoteDesktop-*` by name, then
filter `Enabled` in the pipeline; those parameters belong to different sets.
Windows cannot store wildcard interface aliases: use real `Any` filters for
integration and assert wildcard rejection directly against the same predicate.
Choose a Preferred nonloopback IPv4 assignment paired with one live adapter;
the first up adapter can have no IPv4 address. Create probe scripts exclusively
and set trusted ownership only on the newly created file before the unchanged
owner/ACL guard. A generic owner refusal identifies no offender; retain probe
basename/owner-SID diagnostics and never take ownership of an existing object.

A later full lab refresh refused unverified Tailscale self identity and
deallocated after 150 seconds. A read-only administrator probe found CLI exit
zero, `BackendState=NeedsLogin` and no self IPs; deallocation verified after
118 seconds. A SYSTEM/admin/standard-user comparison deallocated after
201 seconds: SYSTEM and administrator agreed; standard-user CLI/CIM errors
provided no verified backend state. Granting that user more rights is no fix.

SYSTEM-only metadata inspection, without a Tailscale query or file contents,
deallocated after 138 seconds. The original directory/state-file creation
times and SYSTEM/Administrators-only ACLs remained; the state file was written
near the first administrator status query. No provisioner operation targeted
Tailscale state, and Azure activity showed no reimage/disk action. A subsequent
SYSTEM policy/profile-list probe deallocated after 172 seconds: machine
`UnattendedMode=always`, saved account/tailnet profile present but unselected,
and ordinary, unlinked provisioning directories. Metadata does not prove keys
or the historical selection transition; preserve that distinction.

The matching Tailscale v1.104.7 source explains a conditional path: an allowed
non-SYSTEM status request can select an empty administrator default. The
`always` policy saves its forced-daemon preferences and clears startup
selection because the empty profile has no persisted state key. The older
saved profile need not be deleted. The observed policy, unselected profile
and write timing strongly match this path; historical ownership was not logged.
Collect proof only as SYSTEM through the private bounded task, with nonce/SID
verification and owned-task/file cleanup; never fall back to administrator CLI.
SYSTEM execution policy must permit private local task scripts, as for the
fixed recovery task; do not change policy to hide a refused probe.
Diagnose `NeedsLogin` before selecting a profile or reauthenticating. Successful
repair commands alone do not prove unattended persistence: require a cold boot,
SYSTEM running/self-IP evidence and independent private-route proof.

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

## Standard-user task recovery

After host-facts correction, the journal request upload succeeded but
`Start-ScheduledTask YokeQaMachineSettings` returned `Cannot connect to CIM server.
Access denied`. The old screenshot wrapper hid this as a generic `RuntimeError`.
The fixed task already granted the test SID read/run (`GRGX`); do not widen WMI
access or administrator membership to repair a denied CIM connection.

Journal, desktop, terminal and baseline task operations now use the native
Task Scheduler COM interface. Owned tasks use the current SID and limited
interactive logon; foreign tasks remain protected. Reset preserves task XML
and full paths, recreates missing saved folders, and removes newly added owned
tasks. Task failures retain bounded, redacted Scheduler diagnostics.

Runtime uploads also use bounded offset frames and cumulative length/hash
receipts before execution or file commit; failed staging is cleaned up.
Disposable Windows guest checks passed with both Git and native OpenSSH:
the actual standard-SSH journal task returned its restore receipt, task/XML/PATH
reset restored state, a deleted nested task folder was recreated, and attempted
removal of the fixed SYSTEM task was refused. This proves those operations;
full lab readiness still requires live proof. A subsequent registered capture
did execute interactively and produced a real 1024×768 PNG. It showed Windows
first-run privacy setup, not a ready desktop; the lease released and Azure
deallocation verified. Decision request 15878 selects **Windows defaults** to
match a typical user. Complete those prompts before desktop/app acceptance.

## Native feature evidence

Both direct CIM and legacy WMI feature queries returned `Access denied` under
the standard SSH token. The existing fixed SYSTEM **restore** action must
return current `Win32_OptionalFeature` evidence for both
`Microsoft-Windows-Subsystem-Linux` and `VirtualMachinePlatform`; it adds no
new action or test-user privilege. Refresh that fixed program through the full
guest provisioner before binding a new QA lease to the corrected adapter.

Require the current request token, lease, action and a boolean success field.
Require exactly one row for each feature, with integer installation states:
only **Disabled (2)** or **Absent (3)** prove absence. Enabled, missing,
duplicate, malformed or unknown states never pass. Clear cached proof before
rebinding or a machine-settings case; a successful restore refreshes it.
Receipts live in `C:\ProgramData\YokeQa\receipts`, writable only by
SYSTEM/Administrators and readable by the test SID. The writable `requests`
directory cannot hold trusted proof. Provisioning rejects linked paths or
untrusted owners and verifies exact protected ACLs; it never takes ownership.

## Settings journal and interrupted-case recovery

SYSTEM task `YokeQaMachineSettings` accepts only capture/restore with a QA lease
identifier. Its program/journal in `C:\ProgramData\YokeQa\private` are writable
only by Administrators/SYSTEM; the standard user can start it and write
`C:\ProgramData\YokeQa\requests`, never replace the program or its protected
receipts. Before mutations
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
