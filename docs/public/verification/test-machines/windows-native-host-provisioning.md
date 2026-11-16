# Native Windows Test Machine provisioning

This is a lab procedure for native Windows 11, with WSL absent. It does not
establish a Windows support claim. Follow [setup responsibilities](setup-responsibilities.md).
Use the project inventory for host names, subscription, accounts and evidence.
Record each step's machine, date and observed result; mark untested steps unverified.

## 1. Create or identify the VM

Use infrastructure as code or a recorded operator exception. The native Azure
lab was created by hand under an operator exception; it is not an IaC-managed
resource. Keep the exception with the project inventory and eventual import work.
Use Windows 11 Enterprise x64, Trusted Launch, Windows_Client licensing and
at least four CPUs, 16 GiB memory and a 128 GiB OS disk. Windows Server is not
an equivalent desktop-app test target. Confirm the subscription's Windows
client licensing eligibility before creation.

Example Azure CLI sequence, with project-owned names and an approved Windows
11 marketplace image URN from `az vm image list`:

```powershell
az group create --name GROUP --location eastus
az network nsg create --resource-group GROUP --name NSG
az network nsg rule create --resource-group GROUP --nsg-name NSG --name ssh --priority 100 --access Allow --protocol Tcp --source-address-prefixes '*' --destination-port-ranges 22
az network public-ip create --resource-group GROUP --name IP --sku Standard --allocation-method Static
az network vnet create --resource-group GROUP --name VNET --subnet-name SUBNET
az network nic create --resource-group GROUP --name NIC --vnet-name VNET --subnet SUBNET --network-security-group NSG --public-ip-address IP
az vm create --resource-group GROUP --name VM --nics NIC --image IMAGE_URN --size Standard_D4s_v4 --security-type TrustedLaunch --enable-secure-boot true --enable-vtpm true --license-type Windows_Client --admin-username ADMIN --admin-password PASSWORD --os-disk-size-gb 128
```

The final placeholder describes the Azure API input, not a password to paste
into shell history. Generate the machine password in Yoke's local secret store;
invoke Azure from a controller process that reads it privately and redacts
errors. Never print it, put it in an item, commit it, or send it in chat.
Ben enters his own harness and GitHub credentials later.
Create the subscription budget and cost alerts in the same approved creation
operation. A budget is an alert, not a power-off mechanism.

Under the recorded operator exception, create the network and VM with `az`.
Use project-owned names and the authorized subscription; these examples use
the existing `yoke-test-machines` resource group in `eastus`:

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

Install Windows OpenSSH Server using Azure `az vm run-command invoke
--command-id RunPowerShellScript`. Set `sshd` automatic, enable public-key
authentication and disable password authentication in
`C:\ProgramData\ssh\sshd_config`. Authorize the project test-machine public
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

In a Yoke source lane run that through `yoke dev run --allow-real-machine-home
-- ...`; this deliberately persists the generated test-user password in Yoke.
The provisioner uses the capability-owned `test-machine.ssh_private_key` and
stores `test-machine:VM.desktop_password`; it streams the password to the
administrator over SSH stdin. It never embeds it in argv or the provisioned
script. Keep administrator and standard-user passwords separate.
Read errors and rerun only after correcting the named failure. Azure returning
success does not prove its script succeeded; the provisioner requires its
explicit readiness message.

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
