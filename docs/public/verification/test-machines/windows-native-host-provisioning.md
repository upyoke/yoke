# Native Windows Test Machine provisioning

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Native Windows host provisioning
<!-- /yoke:breadcrumbs -->

Native Windows 11 lab procedure, WSL absent; no Windows support claim.
Follow [setup responsibilities](setup-responsibilities.md); use project inventory
for hosts, accounts and evidence. Record observed results; mark untested steps unverified.

## 1. Create or identify the VM

This lab uses a recorded manual exception; retain its inventory/import work.
Require Windows 11 Enterprise x64, Trusted Launch, Windows_Client eligibility,
four CPUs, 16 GiB memory and a 128 GiB OS disk; Server is not a desktop target.

Generate the machine password in Yoke's local secret store; invoke Azure from
a controller that reads it privately and redacts errors. Never put passwords
in argv, shell history, items or chat. Ben enters his own sign-ins later.
Create budget/cost alerts; they do not power off the VM.

Use project-owned names in the authorized subscription; for the existing lab:

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
Slowness alone is not an installation error. Keep the Microsoft-serviced
capability; use a pinned, signature-verified Microsoft MSI only after an
actual capability installation error has been diagnosed.
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

The source-owned provisioner performs those steps for an **existing** VM,
creates the standard test account and its profile, authorizes the same public
key in its `.ssh\authorized_keys`, prepares the golden directory and fixed
recovery task, and enables RDP restricted by the SSH-only network route:

```text
python -m yoke_harness.native_windows.provision --project P --machine VM --host ADDRESS --resource-group GROUP --admin-user ADMIN --test-user yokeqa
```

When administrator key SSH already works, add `--bootstrap-transport ssh` to run
bootstrap through SSH instead of Azure Run Command. The default remains `azure`.
Uploads and password input use bounded length frames, so guest readers finish
without waiting for stdin EOF. Uploaded files require a byte-count and SHA256
receipt before execution; password input never produces a digest or receipt.

In a Yoke source lane run that through `yoke dev run --allow-real-machine-home
-- ...`; this deliberately persists the generated test-user password in Yoke.
The provisioner uses the capability-owned `test-machine.ssh_private_key` and
stores `test-machine:VM.desktop_password`; it streams the password to the
administrator over SSH stdin. It never embeds it in argv or the provisioned
script. Keep administrator and standard-user passwords separate.
Retries preserve an existing test account's password and require its stored
`desktop_password`; restore custody if it is missing, rather than resetting the
account. Profiles are created by the administrator through Windows
[`CreateProfile`](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-createprofile)
with a 260-character output buffer and resolved by SID, including directory
suffixes. Require the registered directory/hive; sign-in remains unproven.
An account can exist without a profile after interrupted setup. Preserve it and
its stored password; rerun the same provisioner with `--bootstrap-transport ssh`.
It resolves `ProfileList\<SID>\ProfileImagePath`, requires `NTUSER.DAT`, and
accepts CreateProfile success or `ERROR_ALREADY_EXISTS` only after validation.
Other HRESULTs, missing custody, a disabled account or unexpected privileges
require investigation; never reset the password or delete/recreate the account.
Correct named failures before retrying; require explicit readiness receipts,
not merely Azure success. Controller SSH uses `-F none` for both Git and native
OpenSSH; Windows `nul` is not a portable SSH config-file argument.

### Bounded recovery when administrator SSH is unavailable

Use an explicitly approved window: one start, maximum twenty minutes, reserve
cleanup at minute seventeen, and verify `PowerState/deallocated` by minute twenty.
Stop on ambiguity; a timeout is not permission to retry or kill guest processes.
If OpenSSH is installed/running but TCP22 is blocked, inspect the managed
`YokeQaSsh` firewall rule. `New-NetFirewallRule` requires `-DisplayName` even
with `-Name`; omitting it can prompt instead of completing noninteractively.
Save this nonsecret repair script as `ssh-firewall.ps1`:

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

Require terminal execution success, exit code zero and `YOKE_SSH_FIREWALL_READY`;
ARM `Creating`/`Canceled` alone is not the guest result. Do not repeat removal or
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

Never kill a reported process. Run the provisioner only after this zero-count
audit, retaining all three readiness receipts. Verify both users' actual token
SIDs against `Get-LocalUser`, and administrator membership true only for ADMIN.
Inspect the test SID's registered path/hive; do not assume a profile directory.

### RDP firewall failure and partial setup

Windows Firewall rejects **both** `::1` and `127.0.0.1` as explicit loopback
address conditions. Do not replace the rejected IPv6 address with an IPv4 allow
rule. The provisioner removes legacy `YokeQaRdpLoopback`, disables stable
`RemoteDesktop-*` rules, requires all firewall profiles enabled/default inbound
block, and refuses other RDP-capable allow rules. Keep NSG public3389 blocked;
forward explicitly with `ssh -i KEY -N -L 127.0.0.1:LOCAL_PORT:127.0.0.1:3389 USER@HOST`.
Require a real forwarded RDP negotiation and independently blocked direct RDP.

The profile-by-SID window failed at this rule and deallocated after 121 seconds.
Registration, QA and an independent profile receipt remained unverified.
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
Install Python 3, Git, Node.js/npm and the project's baseline tools natively.
Do not install WSL, VirtualMachinePlatform or a Linux distro.

## 3. Desktop and sign-ins

Enable the standard user for Remote Desktop. Configure automatic logon for
this dedicated disposable lab account using an LSA-protected password (for
example Microsoft's Sysinternals Autologon), never a plaintext Winlogon
`DefaultPassword`. Disable locking only for this dedicated test desktop under
the project's lab policy. Reboot and prove a scheduled task with
`LogonType=Interactive` runs as the standard user without an RDP client open.

Register `desktop_protocol=rdp`, `desktop_route=ssh-forward`,
`desktop_host=127.0.0.1`, `desktop_port=3389` and `desktop_user=yokeqa`.
`yoke test-machine desktop-access` returns the forwarded address and a private
password-file path; use your existing RDP application. Native Windows does
not add an RDP client to Yoke. Disconnect without signing out; if the desktop
is locked or logged off, reconnect, unlock and return it to the console
session before QA. Screenshots are taken **inside the VM** by a scheduled
task using `CopyFromScreen`, then read back over SSH.

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
Install and launch each vendor's Windows desktop app as the same user.
Agents finish setup and navigation; Ben types his own harness and GitHub
passwords. Prove each CLI makes a real request, and each desktop app visibly
opens and is signed in, before capturing the golden. Install-only and
`--version` checks do not prove account readiness. Follow
[native browser identities](windows-browser-identities.md) for browser sign-ins.

## 4. Settings journal and interrupted-case recovery

The fixed `YokeQaMachineSettings` task runs as SYSTEM. Its program and durable
journal live under `C:\ProgramData\YokeQa\private`, writable only by
Administrators/SYSTEM. The standard test user can write requests under
`C:\ProgramData\YokeQa\requests` and start the task; it cannot replace the
program. The task accepts only capture/restore with a QA lease identifier.
It records the local AppLocker policy, presence/value of `LongPathsEnabled`,
machine certificate inventory and installed Programs/MSI tools **before**
case mutations. It exports the machine public certificates privately.

Before a case removes a baseline tool, the administrator must provide its
versioned installer in the private recovery cache and a
`tool-installers.json` catalog. Never remove a certificate with a private key
without a project-approved private-key recovery procedure. A failed restore
retains the journal and reports its reason; it never becomes a passing case.

Cleanup restores the saved policy, registry value, certificates and tools,
then compares every inventory. The next serial QA lease restores an
interrupted journal before capturing another. Keep the machine unavailable
until restoration verifies. No VM snapshots are used. Do not manually delete
the journal, declare a policy failure passed, or recapture a dirty machine.

## 5. Register, capture and prove

Register only after the VM exists and its standard user works. A native
machine declares `os=windows`; a WSL machine has its own OS kind.
Use a literal Windows path such as `C:\YokeQa\goldens\baseline` outside the
test profile. Settings contain no credentials. Register the provider and
resource identifier using the installed provider power contract, then prove
start, address refresh and deallocation on last QA lease release.

```text
yoke test-machine settings-replace --project P --test-machine NAME --settings-file SETTINGS.json --new
yoke test-machine golden-capture --project P --test-machine NAME --destination C:\YokeQa\goldens\baseline
yoke test-machine verify --project P --test-machine NAME
yoke test-machine screenshot --project P --test-machine NAME
```

Read each command's help before execution. Capture never overwrites an
existing golden. Profile restore mirrors the captured profile, restores user
PATH and the user-task roster, and preserves live harness/browser identities
and locked Windows registry hives. Close test apps before capture/reset;
copy failures leave the capture unsealed. Keep project baseline tools and
fixtures in the project-owned inventory.

Record a scripted check with WSL absent, a real desktop PNG, a profile/PATH/
scheduled-task reset roundtrip, an interrupted policy-case restoration and
the provider's deallocated power state after release. These are machine
receipts, separate from the plan's final integrated Windows acceptance pass.
