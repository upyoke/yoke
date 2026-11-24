# Native Windows Test Machine provisioning

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Native Windows host provisioning
<!-- /yoke:breadcrumbs -->

Follow the [normal-user installation rule](index.md#install-as-the-test-user).

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
### Link the Azure provider identity

Use the existing **yoke-admin** service principal with inventory tenant, client ID,
subscription and grants. VM account `yokeadmin` is separate; interactive `az login`
does not link the provider. Feed secret-set from private custody or
masked operator input, never a literal secret in argv, shell history, captures
or chat. Run:

```text
yoke azure admin-link --project P
yoke projects capability-settings merge --project P --cap-type azure-admin --set tenant_id=TENANT --set client_id=APP_ID --set subscription_id=SUBSCRIPTION
yoke projects capability secret set --project P --cap-type azure-admin --key client_secret --value-stdin
yoke azure admin-status --project P
```

For masked terminal entry, use this instead of the secret-set line above:

```python
import getpass
import subprocess
subprocess.run(
    ["yoke", "projects", "capability", "secret", "set", "--project", "P",
     "--cap-type", "azure-admin", "--key", "client_secret", "--value-stdin"],
    input=getpass.getpass("yoke-admin client secret: "), text=True, check=True,
)
```

Require `admin-status` ready before provider QA. A missing capability can be
reported as a subscription mismatch; compare the inventory resource ID and
`admin-status` before changing either. The provider uses its own principal login.

For rotation, the operator opens Entra **App registrations > yoke-admin >
Certificates & secrets > Client secrets > New client secret**. Set a description
and expiry, add it alongside the old credential, and capture its one-time
**Value** into private custody. Repeat secret-set with that Value, not its ID.
Require ready status and successful provider start/deallocation before deleting
only the old credential by its ID. Retain the existing app and role grants.
See [Microsoft's client-secret steps](https://learn.microsoft.com/en-us/entra/identity-platform/howto-create-service-principal-portal#option-3-create-a-new-client-secret).

### Create or identify the VM resources

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
No public RDP rule exists. Human RDP is reachable over the verified tailnet;
an authenticated SSH forward remains available during bootstrap.
Use Windows Firewall on all network profiles for SSH; do not enable password
SSH or a public desktop listener as a recovery shortcut.

Until provider power is registered and verified, start explicitly before use.
Keep the lab on until setup, sign-ins and QA finish, without countdowns or idle
shutdowns; then **deallocate**, verify actual power state and report it:

```text
az vm start --resource-group GROUP --name VM
az vm deallocate --resource-group GROUP --name VM
```

### Tailscale and public IP lifetime

Follow [tailnet bootstrap](tailnet-bootstrap.md) to start the deallocated VM.
From the standard user's desktop, run the [Tailscale Windows installer](https://tailscale.com/download/windows)
and accept its normal UAC prompt. Have the operator approve the AuthURL and
disable key expiry. Complete
[unattended selection and coldboot proof](windows-native-provisioning-recovery.md#unattended-selection-before-registration)
before registration; resolve the reported MagicDNS name from the controller.
Use the linked bootstrap SSH command with Yoke's known_hosts and the full VM
resource ID as HostKeyAlias. Register MagicDNS as `host`; direct RDP uses
that same tailnet name as `desktop_host`. A forwarded route uses loopback.
Golden reset never changes Tailscale.

Permit RDP only over verified tailnet addresses or interfaces. The installed
Tailscale CLI must report a running self identity **as SYSTEM**; each address needs one
preferred assignment on a live adapter. Every local address or every interface
must be verified. Names, wildcards, broad ranges and mixed public scope do not
prove confinement. Preserve Tailscale; add no blanket 3389 block. Prove tailnet
RDP and blocked public TCP3389; keep public NSG/firewall TCP/UDP3389 closed.
The provisioner uses an owned, bounded SYSTEM task and private filtered receipt,
then removes its task/files. An administrator-context status query can select
a different Windows Tailscale profile; do not use it as a harmless health check.
For `NeedsLogin`, preserve saved profiles and diagnose before reauthentication;
see [the observed recovery](windows-native-provisioning-recovery.md#tailscale-query-context-and-preserved-state).

Register the private MagicDNS name. Keep key-only SSH (TCP 22) and no public
RDP. The Standard public IP supplies outbound traffic and bills until deleted.
Registered power attaches `VM-yoke-power` to the sole NIC IP configuration,
starts the VM and waits for MagicDNS SSH and the lab user's console session. When the final lease releases, the client deallocates the VM and deletes the public IP.
Before registration, attach the bootstrap IP for each start. Use the NIC's
resource group, NIC name and IP configuration name.
`az network nic ip-config update --resource-group NIC_GROUP --nic-name NIC_NAME --name CONFIG_NAME --public-ip-address IP_ID`.
After deallocation, use the same stop procedure's detach and delete commands
with the bootstrap IP.

For existing-VM host/IP cutover, unmanaged-IP failures, host replacement and
DNS/SSH repair, follow [tailnet recovery](windows-native-provisioning-recovery.md#tailnet-cutover-and-host-replacement).

## 2. Provision OpenSSH and the standard test account

Install the Microsoft-serviced Windows capability with
`Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0` using Azure
`az vm run-command invoke --command-id RunPowerShellScript`. Set `sshd` automatic, enable public-key
authentication and disable password authentication in
`C:\ProgramData\ssh\sshd_config`. Fresh Windows images can spend considerable time in Windows Update servicing;
the provisioner announces and allows up to 90 minutes for the capability
bootstrap. Let servicing settle after first boot, then retry when necessary.
Use a pinned, signature-verified MSI only after a diagnosed capability error.
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
probe. Preserve the VM disk and record recovery results. Keep the lab on while
the item needs it; deallocate and verify once setup, sign-ins and QA finish.
See Microsoft's [action Run Command recovery](https://learn.microsoft.com/en-us/azure/virtual-machines/windows/run-command)
and [OpenSSH installation](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse).

Authorize the project test-machine public
key for the administrator bootstrap in
`C:\ProgramData\ssh\administrators_authorized_keys`, owned only by
Administrators/SYSTEM. Validate the effective configuration and restart sshd.

For an **existing** VM the provisioner creates the standard account/profile,
authorizes its `.ssh\authorized_keys`, and enables private RDP over the tailnet
or an SSH forward. It grants inheritable access on `C:\YokeQa` before creating
the golden directory and preserves the ACLs on sealed golden contents:

```text
python -m yoke_harness.native_windows.provision --project P --machine VM --host ADDRESS --resource-group GROUP --admin-user ADMIN --test-user yokeqa
```

When administrator key SSH works, `--bootstrap-transport ssh` uses private
batch SFTP. The controller needs `sftp` beside `ssh`. Preparation, transfer and
hash verification share 90 seconds. The verified script runs through `-File`
with a 300-second budget. Password input stays on framed stdin with concurrent
output draining. Allow four seconds for child termination and thirty for cleanup.
On staging failure, inspect `staging_diagnostics` using the
[native Windows recovery guide](windows-native-provisioning-recovery.md).
SFTP verifies script transfer only; setup still requires actual password-input,
standard-user desktop and SSH proof before readiness is claimed.

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

For administrator-SSH repair, stale-process audit, partial key/RDP
recovery and observed window outcomes, follow
[native Windows provisioning recovery](windows-native-provisioning-recovery.md).
Retain all required receipts before continuing setup or QA.

Prove the test user is not an Administrator and cannot modify the fixed
administrator task or its program. The terminal reader uses interactive-session
`CONOUT$`, including with redirected output, rather than a substituted transcript.
Install [Python 3](https://www.python.org/downloads/windows/) with **Install
for all users** off. Verify `(Get-Command python.exe).Source` is under
`%LOCALAPPDATA%`. Use the vendor defaults with UAC for
[Git](https://git-scm.com/install/windows), [Node.js](https://nodejs.org/en/download)
and Tailscale. Yoke ships the Visual C++ runtime app-local. Keep WSL,
VirtualMachinePlatform and Linux distros absent.

## 3. Desktop and sign-ins

Follow [Native Windows desktop and autologon](windows-native-desktop.md) before installing harnesses and capturing goldens.

## 4. Register, capture and prove

Register after the standard user works, with native `os=windows` separate from
WSL. Use an absolute golden path outside the profile and no credentials in settings.
Register provider/resource ID through the installed power contract. Prove start,
unchanged MagicDNS host and continued operation after lease release.
Set and maintain [capability tags](host-provisioning.md#register-capability-tags) before verifying.

```text
yoke test-machine settings-replace --power-project P --test-machine NAME --settings-file SETTINGS.json --new
yoke test-machine golden-capture --test-machine NAME --destination C:\YokeQa\goldens\baseline
yoke test-machine verify --test-machine NAME
yoke test-machine screenshot --test-machine NAME
```

`shell-preconfigured` runs the released `/install.ps1` as the signed-in desktop
user through an interactive task, the way users install; SSH only verifies.
OpenSSH sessions run under Redirection Guard and cannot follow uv's Python
links: the installer refuses `windows_untrusted_mount_point`, and `yoke update`
and setup rerun it as a one-shot task that needs the desktop user signed in.

Read command help first; never overwrite an existing golden. Restore mirrors
the profile, restores user PATH/tasks and preserves live harness/browser
identities and locked registry hives. Close apps before capture/reset; copy
failures leave capture unsealed. Keep baseline tools/fixtures in project inventory.

Record a scripted check with WSL absent, a real desktop PNG, a profile/PATH/
scheduled-task reset roundtrip, an interrupted policy-case restoration and
the provider's running power state after release. These are machine
receipts, separate from the plan's final integrated Windows acceptance pass.
