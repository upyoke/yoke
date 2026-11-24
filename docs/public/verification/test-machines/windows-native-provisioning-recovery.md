# Native Windows provisioning recovery

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Native Windows provisioning recovery
<!-- /yoke:breadcrumbs -->

Return to [native Windows setup](windows-native-host-provisioning.md) for
Azure identity, normal provisioning, registration and the remaining QA steps.
Keep every failed-window receipt and verified power state with the inventory.

## Recovery when administrator SSH is unavailable

Keep the lab on through setup, sign-ins and QA, without countdowns or idle
deallocation. Then deallocate, verify `PowerState/deallocated` and report it.
Keep commands bounded; stop on ambiguity. Timeouts never authorize process kills.
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
Register **SETUP INCOMPLETE** and continue setup, sign-ins and QA with the lab
on. On failure, stop that operation and inspect the exact guest error; never
mark registration or QA complete. Deallocate when the item no longer needs it.

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
An unmanaged IP attachment refuses with that recovery. Verify that the VM stays
running, the MagicDNS host is unchanged and the QA_HOST lease has been released.
Use [manual stop commands](host-provisioning.md#stop-a-cloud-test-machine) when
the lab is no longer needed; verify deallocation and public-IP removal then.

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
Task completion can race `Stop()`: accept only `SCHED_E_TASK_NOT_RUNNING`
(`0x8004130B`), then require fresh settled state before deleting task/files.
Queued instances get one owned-task stop fallback; other errors or unsettled
state preserve the task/files and report cleanup alongside the original error.

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
SYSTEM execution policy must permit private local task scripts; do not
change policy to hide a refused probe.
Diagnose `NeedsLogin` before selecting a profile or reauthenticating. Successful
repair commands alone do not prove unattended persistence: require a cold boot,
SYSTEM running/self-IP evidence and independent private-route proof.

### Unattended selection before registration

Fresh hosts must complete this checkpoint after the SYSTEM unattended join and
operator authentication, before registration. Keep every Tailscale CLI query
as SYSTEM; the provisioner's private SYSTEM probe prevents administrator
health checks from selecting another profile. Follow the lab lifetime policy
above and use an operator-approved local profile display label `LABEL`.

1. Capture `tailscale switch --list --json` and `tailscale status --json` only
   in memory as SYSTEM. Require exactly one selected saved profile, `Running`,
   `HaveNodeKey=true`, the expected node identity and self addresses with
   Preferred assignments on live adapters. Stop on refusal or unavailable auth.
2. Give the joined profile its approved label with
   `tailscale set --nickname=LABEL`, only when the listed nickname differs.
   This genuine edit forces a preference save; step 3 verifies the unattended
   startup target. It changes profile display metadata, not hostname, auth or policy.
   A repeated identical preference can be a no-op. If the label already matches
   but startup selection is absent, stop for a different approved label.
3. Recheck selected profile, label, unchanged node/key and live addresses.
   For the observed FileStore version, check only presence/nonempty metadata
   for `server-mode-start-key` in protected `server-state.conf`; its JSON value
   is Base64 bytes. Never print values, dump preferences or edit state files.
   Require the startup target, not just command exit zero.
4. When the explicit cold-boot verification is ready, record the guest boot
   time, deallocate and verify actual `PowerState/deallocated`. Start again;
   require a fresh boot time different from the first. Without selection,
   preference or provisioning changes, verify the same selected profile/label,
   startup target, SYSTEM Running/key/live-address proof, standard-user tailnet
   SSH and direct RDP TLS/NLA, plus blocked public3389. Keep the lab on for
   remaining setup, sign-ins and QA; deallocate and verify when all are done.
   Only these independent receipts establish unattended persistence.

Existing-profile recovery needs explicit scope before selecting a saved
profile or changing its label. Do not repeat `up`, force authentication,
override policy, take ownership or use `down` as an automatic repair.
Retain fixed invocation stages, exit codes and output byte counts on refusal;
classify exact known errors in memory, never emit raw CLI/state contents.

Observed recovery selected the saved profile and reached Running/private
routes, but unchanged `set --unattended=true` did not survive a distinct boot:
the two windows deallocated in 273/183 seconds. SYSTEM metadata then measured
the profile present/unselected and startup key absent (167 seconds). A guarded
stop/start attempt refused without identifying its stage (232 seconds); the
next read-only check found the active unselected profile NeedsLogin/no key
(173 seconds), which did not prove saved credentials were deleted.

An instrumented attempt proved the saved profile/key/node/live addresses
before `down` refused: exit1, stdout0 bytes, stderr47 bytes (208 seconds).
The pinned Windows disconnect-owner refusal has that exact length, but byte
count alone does not prove its text or profile owner. No `up` followed.
The approved genuine nickname edit then preserved identity and restored the
startup target and private routes passed. The edit window ended with verified
deallocation after 192 seconds.
A distinct read-only coldboot retained profile/label/startup target and passed
live identity/private routes/public denial; deallocation verified at 252 seconds.
No fresh login, disconnect, policy override or direct state edit was needed
for that successful repair. Desktop/tools/sign-ins/goldens/native QA remain.

See [tray startup and autologon](windows-native-desktop.md#tray-startup-and-autologon)
for guarded shortcut handling and the two required cold-boot proofs.

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

Desktop, terminal and baseline task operations now use the native
Task Scheduler COM interface. Owned tasks use the current SID and limited
interactive logon; foreign tasks remain protected. Reset preserves task XML
and full paths, recreates missing saved folders, and removes newly added owned
tasks. Task failures retain bounded, redacted Scheduler diagnostics.

Runtime uploads use bounded offset frames and cumulative length/hash receipts.
Cleanup failure refuses with `windows_admin_staging_cleanup_failed`; completed
command diagnostics remain privately on the exception's `primary_result`.
Restore administrator SSH, inspect those diagnostics privately, then verify
this invocation's owned staging removal before retrying. A cleanup timeout
does not prove the primary command failed or that guest removal hung.
Disposable Windows guest checks passed with both Git and native OpenSSH:
task/XML/PATH reset restored state, a deleted nested task folder was recreated,
and attempted removal of a foreign SYSTEM task was refused. This proves those operations;
full lab readiness still requires live proof. A subsequent registered capture
did execute interactively and produced a real 1024×768 PNG. It showed Windows
first-run privacy setup, not a ready desktop; the lease released and Azure
deallocation verified. Decision request 15878 selects **Windows defaults** to
match a typical user. A later observed private Windows App session accepted
those displayed defaults and reached the Windows 11 desktop. Desktop/app
acceptance and the remaining lab proof are still required.
