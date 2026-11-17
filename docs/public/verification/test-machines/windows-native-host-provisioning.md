# Native Windows Test Machine provisioning

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Native Windows host provisioning
<!-- /yoke:breadcrumbs -->

Native Windows 11 lab procedure, WSL absent; no Windows support claim.
Follow [setup responsibilities](setup-responsibilities.md); inventory holds
hosts/accounts/evidence. Record results; mark untested steps unverified.

## 1. Create or identify the VM

Retain the lab's manual exception and inventory/import work. Require Windows 11
Enterprise x64, Trusted Launch, Windows_Client eligibility, 4 CPUs, 16 GiB RAM
and a 128 GiB OS disk; Server is not a desktop target.

Generate the machine password in Yoke's local secret store; invoke Azure from
a controller that reads it privately and redacts errors. Never put passwords
in argv, shell history, items or chat. Ben enters his own sign-ins later.
Create budget/cost alerts; they do not power off the VM.

If `az` fails with `AADSTS530035` (security defaults), the operator completes
interactive `az login --tenant TENANT --scope https://management.core.windows.net//.default`
and selects the inventory subscription. The lane retries the failed read,
requires a fresh power-state receipt, then resumes; never bypass the policy.

```text
az network vnet create -g yoke-test-machines -n windows-native-lab-vnet --subnet-name default
az network nsg create -g yoke-test-machines -n windows-native-lab-nsg
az network nsg rule create -g yoke-test-machines --nsg-name windows-native-lab-nsg -n ssh --priority 100 --access Allow --protocol Tcp --source-address-prefixes '*' --destination-port-ranges 22
az network public-ip create -g yoke-test-machines -n windows-native-lab-ip --sku Standard --allocation-method Static
az network nic create -g yoke-test-machines -n windows-native-lab-nic --vnet-name windows-native-lab-vnet --subnet default --network-security-group windows-native-lab-nsg --public-ip-address windows-native-lab-ip
```

Use `az rest --method put --url VM_RESOURCE_ID?api-version=2024-07-01
--body @PRIVATE_VM_REQUEST.json` for VM creation, with the private request
constructed from the generated password already stored by Yoke. Its
`properties` declare `hardwareProfile.vmSize=Standard_D4s_v4`, the NIC resource
id under `networkProfile.networkInterfaces`, `licenseType=Windows_Client`,
`securityProfile.securityType=TrustedLaunch`, both `uefiSettings.secureBootEnabled`
and `vTpmEnabled=true`, and `osProfile` with the generated administrator
credential. `storageProfile.imageReference` is
`MicrosoftWindowsDesktop:windows-11:win11-25h2-ent:latest`; use a 127 GiB
`StandardSSD_LRS` managed OS disk with `createOption=FromImage`. Keep the
request owner-only outside the checkout, never capture its contents, and
delete it after the request. Verify the resulting resource with a query that
returns only its id, image, disk size, security type and power state.

SSH port 22 is reachable from any address, with **key-only authentication**.
No public RDP rule exists. RDP is for humans over an authenticated SSH forward.
Use Windows Firewall on all network profiles for SSH; do not enable password
SSH or a public desktop listener as a recovery shortcut.

Until provider power is registered and verified, start explicitly before use
and **deallocate**, rather than merely stop, after use:

```text
az vm start --resource-group GROUP --name VM
az vm deallocate --resource-group GROUP --name VM
```

## 2. Provision OpenSSH and the standard test account

Install the Microsoft-serviced Windows capability with
`Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0` using Azure
`az vm run-command invoke --command-id RunPowerShellScript`. Set `sshd` automatic, enable public-key
authentication and disable password authentication in
`C:\ProgramData\ssh\sshd_config`. Fresh Windows images can spend considerable time in Windows Update servicing;
the provisioner announces and allows up to 90 minutes for the capability
bootstrap. Let servicing settle after first boot, then retry when necessary.
Use a pinned, signature-verified Microsoft MSI only after a diagnosed capability error.
If Azure repeatedly refuses a new invocation with “Run command extension
execution is in progress” after the bounded wait, stop the controller retry
loop and record the stuck invocation. Check the VM agent and the invocation's
status before recovery. A stopped controller does not cancel the guest script.
Use Microsoft's special removal command for a stuck **action Run Command**:

```text
az vm run-command invoke --command-id RemoveRunCommandWindowsExtension --resource-group GROUP --name VM
```

For a **managed Run Command**, delete its named resource with
`az vm run-command delete --resource-group GROUP --vm-name VM --name COMMAND_NAME`
instead. These are different Azure resources; select the one actually used.
Action Run Command can have no resource in the VM's ARM extension list;
an empty list does not prove that its guest handler or invocation is absent.
Do not try to delete a nonexistent ARM extension. Wait for the single removal
action to settle; a controller timeout does not prove removal completed.
Let first-boot Windows servicing finish, then rerun the capability provisioner
with its 90-minute bound. Removing the extension does not prove that Windows
servicing stopped or OpenSSH installed; require the readiness receipt and SSH
probe. Preserve the VM disk, deallocate after use, and record recovery results.
See Microsoft's [action Run Command recovery](https://learn.microsoft.com/en-us/azure/virtual-machines/windows/run-command)
and [OpenSSH installation](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse).

Authorize the project test-machine public
key for the administrator bootstrap in
`C:\ProgramData\ssh\administrators_authorized_keys`, owned only by
Administrators/SYSTEM. Validate the effective configuration and restart sshd.

For an **existing** VM the provisioner creates the standard account/profile,
authorizes its `.ssh\authorized_keys`, prepares goldens and the fixed recovery
task, and enables RDP through SSH forwarding:

```text
python -m yoke_harness.native_windows.provision --project P --machine VM --host ADDRESS --resource-group GROUP --admin-user ADMIN --test-user yokeqa
```

When administrator key SSH already works, add `--bootstrap-transport ssh` to run
bootstrap through SSH instead of Azure Run Command. The default remains `azure`.
Script uploads use 2048-byte frames, expected offsets and cumulative SHA256
receipts under one 30-second deadline; only the complete verified script runs.
Owned staging cleanup is bounded to ten seconds and preserves prior errors.
Password frames never produce digests; readers do not wait for stdin EOF.

In a Yoke source lane run that through `yoke dev run --allow-real-machine-home
-- ...`; this deliberately persists the generated test-user password in Yoke.
The provisioner uses the capability-owned `test-machine.ssh_private_key` and
stores `test-machine:VM.desktop_password`; it streams the password to the
administrator over SSH stdin. It never embeds it in argv or the provisioned
script. Keep administrator and standard-user passwords separate.
Preserve existing non-admin accounts and `desktop_password` custody. For
partial setup rerun `--bootstrap-transport ssh`; never reset/recreate the
account. The administrator uses
[`CreateProfile`](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-createprofile)
with a 260-character output buffer and resolves
`ProfileList\<SID>\ProfileImagePath`, Success or `ERROR_ALREADY_EXISTS`
requires the registered directory and `NTUSER.DAT`; sign-in remains
unproven. Investigate other HRESULTs, disabled accounts or unexpected
privileges without changing credentials. Join the existing `OpenSSH Users`
group and verify SID membership; retain sshd's Allow/Deny policy. Apply
directory OI/CI grants **without** recursive inheritance removal, then
plain `F` grants directly to `authorized_keys` for the user, SYSTEM and
Administrators. Check native exits and the actual owner/DACL; recursive
directory-style grants left the key file's DACL empty in CI. Controller SSH
uses `-F none` for both Git and native OpenSSH; Windows `nul` is not a
portable SSH config-file argument.
For an existing key file, validate its trusted owner and repair explicit file
grants **before** writing; an empty protected DACL otherwise denies the write.
Keep final owner/exact-three-SID ACL checks; never take ownership/reset accounts.

### Bounded recovery when administrator SSH is unavailable

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
retain all three readiness receipts. Compare actual token SIDs to `Get-LocalUser`,
admin membership true only for ADMIN, and inspect the test SID's registered path/hive.

### RDP firewall failure and partial setup

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

Prove the test user is not an Administrator and cannot modify the fixed
administrator task or its program. Select **Windows Console Host** as the
default terminal for this dedicated account; the terminal bridge reads its
real console screen, rather than a transcript substituted for the desktop.
Install Python 3, Git, Node.js/npm and baseline tools natively; no WSL,
VirtualMachinePlatform or Linux distro.

## 3. Desktop and sign-ins

Configure automatic logon using an LSA-protected password (such as Microsoft's
Sysinternals Autologon), never a plaintext Winlogon `DefaultPassword`. Disable locking only for this dedicated test desktop under
the project's lab policy. Reboot and prove a scheduled task with
`LogonType=Interactive` runs as the standard user without an RDP client open.

Register `desktop_protocol=rdp`, `desktop_route=ssh-forward`,
`desktop_host=127.0.0.1`, `desktop_port=3389`, `desktop_user=yokeqa`.
`yoke test-machine desktop-access` returns the forward and private password-file
path for your existing RDP client; Yoke adds none. Disconnect without sign-out;
if locked/logged off, reconnect, unlock and return to console before QA.
Scheduled `CopyFromScreen` screenshots run **inside the VM**, read over SSH.

As the standard user install all harness CLIs from their vendors:

```powershell
irm https://claude.ai/install.ps1 | iex
npm.cmd install --global @openai/codex
irm 'https://cursor.com/install?win32=true' | iex
claude --version
codex --version
agent --version
```

Sources: [Claude](https://code.claude.com/docs/en/setup),
[Codex on Windows](https://developers.openai.com/codex/windows/),
[Cursor native CLI](https://cursor.com/docs/cli/installation).
Install/launch each vendor's desktop app as the same user. Agents finish setup
and navigation; Ben types his own harness/GitHub passwords. Before goldens,
prove real CLI requests and visible signed-in desktop apps; installs/versions
alone do not prove readiness. Follow [native browser identities](windows-browser-identities.md).

## 4. Settings journal and interrupted-case recovery

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

## 5. Register, capture and prove

Register only when the VM exists and its standard user works: `os=windows`
for native, a separate OS kind for WSL. Goldens use a literal Windows path
outside the profile, such as `C:\YokeQa\goldens\baseline`; settings contain no
credentials. Register provider/resource ID using the installed power contract;
prove start, address refresh and deallocation on last QA lease release.

```text
yoke test-machine settings-replace --project P --test-machine NAME --settings-file SETTINGS.json --new
yoke test-machine golden-capture --project P --test-machine NAME --destination C:\YokeQa\goldens\baseline
yoke test-machine verify --project P --test-machine NAME
yoke test-machine screenshot --project P --test-machine NAME
```

Read command help first; never overwrite an existing golden. Restore mirrors
the profile, restores user PATH/tasks and preserves live harness/browser
identities and locked registry hives. Close apps before capture/reset; copy
failures leave capture unsealed. Keep baseline tools/fixtures in project inventory.

Record a scripted check with WSL absent, a real desktop PNG, a profile/PATH/
scheduled-task reset roundtrip, an interrupted policy-case restoration and
the provider's deallocated power state after release. These are machine
receipts, separate from the plan's final integrated Windows acceptance pass.
