# Test Machine provisioning

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Host provisioning
<!-- /yoke:breadcrumbs -->

Follow the [normal-user installation rule](index.md#install-as-the-test-user).

For stored-password setup commands on macOS and Linux, follow [administrator commands](administrator-commands.md).

Follow [setup responsibilities](setup-responsibilities.md) for every step.

Before these steps, read the project's declared manual baseline inventory and
preparation procedure. The project owns required packages, runtime choices,
network bindings and extra probes; Yoke does not impose one baseline on
other projects. Complete that manual preparation before capture, retaining all
applicable account, sign-in, privacy and desktop checks below. A Docker CLI alone
is not a responding daemon, Compose v2 or a successful container workload.

Choose one complete ordered procedure. Each covers account and network
preparation, capability/secret registration, tooling and operator sign-in,
desktop control, saving and proving a restorable baseline, and recovery.
Each numbered step carries named-machine/date audit evidence or an explicit
unverified label; code-reviewed contracts do not substitute for live proof.

- [macOS](macos-host-provisioning.md)
- [Linux](linux-host-provisioning.md)
- [Windows with WSL2](windows-host-provisioning.md)
- [Native Windows lab machine](windows-native-host-provisioning.md)
- [Native Windows browser identities](windows-browser-identities.md)

## Register capability tags

Record the host's `os` and optional `capability_tags` in its non-secret settings
JSON. Tags are comma-separated text, for example
`"capability_tags": "arch:x64,codex-desktop-signed-in"`. Add tags only after
proving the capability under the test user. Add or remove a sign-in tag when
the desktop app signs in or out. Update hardware or tool tags when they change.

Register with `yoke test-machine settings-replace --test-machine NAME
--settings-file FILE --new`. To change an existing host, read `yoke test-machine
get --test-machine NAME --json`, copy its complete settings into the file, and
replace `--new` with `--base SETTINGS_TOKEN` using the as-read token. Run
`yoke test-machine verify --test-machine NAME` after saving. Automatic QA
matches `method_config.os` and every tag in the case's `method_config.capability_tags`
array, then selects a verified, healthy host. A slotted case maps each slot OS to
its tags instead, such as `{"macos":["macos:15"]}`.

## Network access

Install Tailscale on every Test Machine, Macs included, join the operator tailnet,
and register its verified MagicDNS name. Controllers join the same tailnet.
Follow the one-time manual setup in each OS guide. Windows runs Tailscale unattended on the
Windows host only, never WSL. Disable device key expiry for unattended access.

Keep OpenSSH reachable from every internet source with public-key authentication
only; disable password and keyboard-interactive authentication. Use the current
dynamic public IP only for bootstrap SSH, with the cloud instance id as
`HostKeyAlias`; never register it. Audit effective sshd and firewall policy.
Golden reset never changes Tailscale state.

Desktops have two routes; neither opens RDP or VNC to the public internet:

- `desktop_route=direct` is the default for a host on the tailnet (or another
  private network). The controller connects to the registered MagicDNS `host`
  itself; leave `desktop_host` unset. On a physical Mac, verify the SSH
  fingerprint at the console and pin it under that hostname before setup. Each OS guide's one-time setup lets the
  desktop listen on the tailnet and confines it there with the host firewall.
  A direct RDP route pins the host's self-signed certificate on first use under
  the Yoke home (`test-machine/rdp_certificates`); a changed certificate refuses
  `desktop_certificate_changed` and names the pin line to delete when the change
  was deliberate.
- `desktop_route=ssh-forward` is the fallback for a host reached only by its
  public SSH address, for people who cannot use Tailscale. `desktop-access`
  holds an `ssh -N -L` forward to the host's loopback desktop while it runs and
  closes it on Enter, Ctrl-C or SIGTERM; a viewer closes it with its window.

Keep cloud security groups and network security groups closed to RDP (3389,
3390) and VNC (5900) from every public source.
Before rebuild, remove the old tailnet device, join again and verify the name
has no `-1` suffix; clear the old host-key pin after verifying the new fingerprint.

Test Machines are registered once in the universe. Every project can request
the same host, and each host has one serial lease shared by all projects.
Cloud machines name a power project with `--power-project P` on
`yoke test-machine settings-replace`. That project's cloud admin credentials
stay in their project capability store.

Baseline restores clear test-account-owned Yoke, Playwright, Chromium and pip
run artifacts from system and OS user temporary locations, preserving the
golden directory and sidecars, live browser identity store and restored home.
The receipt reports removed entries and `temp_cleanup.freed_bytes`. Reset and
verify refuse `test_machine_cleanup_live_lease` while a mission owns the host;
finish or abort it before resetting. Every mission requires 1 GiB free on the
home and temporary filesystems (the system drive on native Windows) before
packages or scratch are staged.
`test_machine_disk_space_low` records the minimum and observed space; finish
or abort the mission, run `yoke test-machine reset --test-machine NAME`,
and grow the disk as in [disk sizing and online resize](#disk-sizing-and-online-resize)
if reset cannot recover the required space. Read reset `--help` before running it.

A failed native request keeps its diagnosed reason and recovery. Quota waits for
provider capacity, transport waits for service recovery, and authentication
advice requires native auth evidence. Unknown nonzero failures need local
diagnostics. Preserve the failed capture and golden; a failure never seals.

Never delete or move a registered golden or its sidecars by hand, including
through `yoke test-machine exec`. Registrations for the same host and user
can keep separate goldens. To replace a golden, run
`yoke test-machine golden-capture --test-machine NAME`. Capture removes
retired snapshots while preserving those still registered. If a registered
golden is missing, `verify` reports `registered_golden_missing` with the
machine name and path so you can capture its replacement.

## Disk sizing and online resize

Give every macOS and Linux Test Machine at least 40 GiB on the volume that
holds the test home and temporary directories. That space holds the OS,
desktop and Chromium, a 3-4 GiB test home, one golden, a second home-sized
copy while a golden is captured, harness installs, mission scratch and the
1 GiB mission admission floor. A 20 GiB Linux root filled repeatedly.

Check usage, then grow online without a reboot. Linux on AWS, as administrator
of the account that owns the volume, then on the host:

```text
yoke test-machine exec --test-machine NAME -- df -h / /tmp
aws ec2 modify-volume --volume-id VOLUME_ID --size 40
aws ec2 describe-volumes-modifications --volume-ids VOLUME_ID
yoke test-machine exec --test-machine NAME --admin -- growpart /dev/nvme0n1 1
yoke test-machine exec --test-machine NAME --admin -- resize2fs /dev/nvme0n1p1
```

Wait for the modification state `optimizing` or `completed` before
`growpart`. Read the device and partition from `lsblk`; use
`xfs_growfs /` instead of `resize2fs` on XFS. Declare the new size in the
project's IaC or record it as an explicit operator exception.

An EC2 Mac grows the same way after `modify-volume`; then, with the disk and
APFS container read from `diskutil list physical external`:

```text
yoke test-machine exec --test-machine NAME --admin -- sh -c 'yes | diskutil repairDisk DISK'
yoke test-machine exec --test-machine NAME --admin -- diskutil apfs resizeContainer CONTAINER 0
```

`yes` answers the `repairDisk` confirmation. A physical Mac's internal disk
cannot grow: free space with reset and old-golden retention, or move to a
larger machine. Confirm with `df -h` and rerun the refused QA.

## Cloud power by lease

Optional `cloud_instance_id` makes Yoke start the VM before host operations,
including `yoke test-machine verify`. `cloud_provider` selects `aws` (the
default) or `azure`. Store these fields in the settings JSON passed to
`yoke test-machine settings-replace`. AWS uses an EC2 instance id; Azure uses
`/subscriptions/SUB/resourceGroups/GROUP/providers/Microsoft.Compute/virtualMachines/VM`.
The Azure VM must belong to the subscription declared by `azure-admin`.

Run `yoke azure admin-link --project PROJECT` for service-principal setup.
Set `tenant_id`, `client_id` and `subscription_id` on the `azure-admin`
capability; store `client_secret` with `yoke projects capability secret set
--project PROJECT --cap-type azure-admin --key client_secret --value-stdin`.
The secret stays in the executing machine's capability secret store. Install
[Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), then run
`yoke azure admin-status --project PROJECT`. It reports missing settings or
credentials and verifies the selected identity. `yoke azure exec --project
PROJECT -- <az-args>` uses those credentials with a disposable private login
cache, independent of the operator's Azure CLI account.

Deploy the provider-capable serving build before registering `cloud_provider`:
older validators reject unknown settings; the CLI names
`test_machine_cloud_provider_serving_floor_required` (minimum serving version
`next-release`). Existing AWS settings work without the optional field.

Yoke starts a stopped instance under its host lease and waits for SSH on the
registered MagicDNS name. When Yoke starts it, Yoke records a power marker.
The releasing client stops a marked instance while holding the host lease
and clears the marker after the provider confirms the stop. A queued
handoff keeps the marker and the instance running. Already-running instances
with no marker stay running. A manual stop and restart before a Yoke-confirmed
stop can leave the marker set.
`yoke test-machine exec`, desktop access and browser authorization each take
the host's lease for their duration (or borrow the caller's own), power a
stopped host on, and release afterwards; a foreign lease refuses them. EC2 uses auto-assigned
public IPv4 while running; no Elastic IP. Azure keeps the private subnet: its
sole NIC IP configuration receives a Standard public IP named `VM-yoke-power`
created on start to supply outbound access. Standard public IPs are static and
bill while they exist.
Keep NSG TCP22 open from anywhere and desktop ports closed. The one-time IP/NSG setup uses the recorded operator exception.
A permanent attachment refuses as unmanaged; detach/delete it after deallocation.

For existing machines, join the tailnet first, deploy the no-rebind build, then
settings-replace `host` with MagicDNS using the as-read token. Only afterward
detach/delete the permanent Azure IP (existing native lab: `20.124.243.250`).
Re-registering before deploy permits an old client to rebind to public IPv4.
Upgrade clients: retired host_rebind calls refuse `function_version_skew` with a
required client floor. The target-changed guard still refuses a changed lease
target. Run `yoke test-machine verify` and confirm the registered host stays
unchanged. If Yoke started the VM and the host queue is empty, the provider
reports it stopped after release.

## Import Test Machine credentials

Import secrets on every controller that executes work on the Test Machine.
The CLI stores them under `~/.yoke/secrets/capability-secrets/test-machines/NAME/`.

```text
yoke test-machine secret set --test-machine NAME --key ssh_private_key --value-file KEY_FILE
yoke test-machine secret set --test-machine NAME --key desktop_password --value-file PASSWORD_FILE
```

At cutover, use the previous owning project's `test-machine/ssh_private_key`
file under `~/.yoke/secrets/capability-secrets/PROJECT/` as `KEY_FILE`.
Import it separately for each machine that used the shared key. Import an
existing named desktop password from `test-machine_NAME/desktop_password`
under that same project directory. Run `yoke test-machine get --test-machine NAME`
on each controller to check the required files are present. Retire the old
paths after controllers use the new build.

### Stop a cloud Test Machine

Coordinate with the host's users and hold its QA_HOST lease during a manual
shutdown so another session cannot start work on it. On EC2, stop the instance:

```text
yoke aws exec --project P -- ec2 stop-instances --instance-ids INSTANCE_ID
```

On Azure, deallocate the VM, then detach and delete its `VM-yoke-power`
public IP. In Azure, open the VM's network interface and find the IP
configuration that references this public IP. Use the NIC's resource group,
NIC name and IP configuration name for the detach command. If a network
command fails, inspect its error, repair the named
permission or resource and retry the failed step.

```text
yoke azure exec --project P -- vm deallocate --ids VM_RESOURCE_ID
yoke azure exec --project P -- network nic ip-config update --resource-group NIC_GROUP --nic-name NIC_NAME --name CONFIG_NAME --public-ip-address null
yoke azure exec --project P -- network public-ip delete --ids IP_ID
```

Release the lease after checking the provider state and, on Azure, that the
public IP is gone. The next Yoke operation that needs the machine starts it.
