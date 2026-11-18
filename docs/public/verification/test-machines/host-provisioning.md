# Test Machine provisioning

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Host provisioning
<!-- /yoke:breadcrumbs -->

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

## Network access

Install Tailscale on every Test Machine, Macs included, join the operator tailnet,
and register its verified MagicDNS name. Controllers join the same tailnet.
Follow the one-time manual setup in each OS guide. Windows runs Tailscale unattended on the
Windows host only, never WSL. Disable device key expiry for unattended access.

Keep OpenSSH reachable from every internet source with public-key authentication
only; disable password and keyboard-interactive authentication. Use the current
dynamic public IP only for bootstrap SSH, with the cloud instance id as
`HostKeyAlias`; never register it. Forward desktops over SSH
(`desktop_route=ssh-forward`); open no public RDP/VNC port. Audit effective sshd,
firewall policy. Golden reset never changes Tailscale state.
Before rebuild, remove the old tailnet device, join again and verify the name
has no `-1` suffix; clear the old host-key pin after verifying the new fingerprint.

Hostnames, account names, infrastructure and credentials are project-owned.
These procedures ship with Yoke; project records own the host inventory.

Baseline restores clear test-account-owned Yoke, Playwright, Chromium and pip
run artifacts from system and OS user temporary locations, preserving the
golden directory and sidecars, live browser identity store and restored home.
The receipt reports removed entries and `temp_cleanup.freed_bytes`. Reset and
verify refuse `test_machine_cleanup_live_lease` while a mission owns the host;
finish or abort it before resetting. Every mission requires 1 GiB free on the
home and temporary filesystems before packages or scratch are staged.
`test_machine_disk_space_low` records the minimum and observed space; finish
or abort the mission, run `yoke test-machine reset --project P --test-machine NAME`,
and grow the disk as in [disk sizing and online resize](#disk-sizing-and-online-resize)
if reset cannot recover the required space. Read reset `--help` before running it.

A failed native request keeps its diagnosed reason and recovery. Quota waits for
provider capacity, transport waits for service recovery, and authentication
advice requires native auth evidence. Unknown nonzero failures need local
diagnostics. Preserve the failed capture and golden; a failure never seals.

Never delete or move a registered golden or its sidecars by hand, including
through `yoke test-machine exec`. Every project that registers the same host
and user keeps its own golden there and resets from it. To replace a golden,
run `yoke test-machine golden-capture`; its retention removes retired
snapshots. `yoke test-machine verify` refuses `registered_golden_missing`,
naming each project and path whose golden is gone; capture a new golden for
that project.

## Disk sizing and online resize

Give every macOS and Linux Test Machine at least 40 GiB on the volume that
holds the test home and temporary directories. That space holds the OS,
desktop and Chromium, a 3-4 GiB test home, one golden, a second home-sized
copy while a golden is captured, harness installs, mission scratch and the
1 GiB mission admission floor. A 20 GiB Linux root filled repeatedly.

Check usage, then grow online without a reboot. Linux on AWS, as administrator
of the account that owns the volume, then on the host:

```text
yoke test-machine exec --project P --test-machine NAME -- df -h / /tmp
aws ec2 modify-volume --volume-id VOLUME_ID --size 40
aws ec2 describe-volumes-modifications --volume-ids VOLUME_ID
yoke test-machine exec --project P --test-machine NAME --admin -- growpart /dev/nvme0n1 1
yoke test-machine exec --project P --test-machine NAME --admin -- resize2fs /dev/nvme0n1p1
```

Wait for the modification state `optimizing` or `completed` before
`growpart`. Read the device and partition from `lsblk`; use
`xfs_growfs /` instead of `resize2fs` on XFS. Declare the new size in the
project's IaC or record it as an explicit operator exception.

An EC2 Mac grows the same way after `modify-volume`; then, with the disk and
APFS container read from `diskutil list physical external`:

```text
yoke test-machine exec --project P --test-machine NAME --admin -- sh -c 'yes | diskutil repairDisk DISK'
yoke test-machine exec --project P --test-machine NAME --admin -- diskutil apfs resizeContainer CONTAINER 0
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

Power starts the instance without reading or writing the registered host, then
waits for SSH on MagicDNS. Last release stops EC2 or **deallocates** Azure under
the host's lease; a reserved waiter's turn keeps it running.
`yoke test-machine exec`, desktop access and browser authorization each take
the host's lease for their duration (or borrow the caller's own), power a
stopped host on, and release afterwards; a foreign lease refuses them. EC2 uses auto-assigned
public IPv4 while running; no Elastic IP. Azure keeps the private subnet: its
sole NIC IP configuration receives a Standard public IP named `VM-yoke-power`
created on start, detached/deleted after deallocation, supplying outbound access.
Basic public IP is retired; Standard is static and bills while it exists.
A failed IP delete reports `test_machine_power_stop_failed`; repair permissions
and retry verify/release, then confirm the IP is gone, even if already deallocated.
Keep NSG TCP22 open from anywhere and desktop ports closed. The one-time IP/NSG setup uses the recorded operator exception.
A permanent attachment refuses as unmanaged; detach/delete it after deallocation.

For existing machines, join the tailnet first, deploy the no-rebind build, then
settings-replace `host` with MagicDNS using the as-read token. Only afterward
detach/delete the permanent Azure IP (existing native lab: `20.124.243.250`).
Re-registering before deploy permits an old client to rebind to public IPv4.
Upgrade clients: retired host_rebind calls refuse `function_version_skew` with a
required client floor. The target-changed guard still refuses a changed lease
target; do not bypass it. Stop each cloud lab, run `yoke test-machine verify`,
and prove unchanged host, no remaining QA_HOST and no Azure public IP afterward.
A release no client hears leaves the VM running until its next lease cycles;
there is no idle sweep.
