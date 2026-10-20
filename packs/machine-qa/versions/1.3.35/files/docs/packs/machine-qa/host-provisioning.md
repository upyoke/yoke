# Test Machine provisioning

For stored-password setup commands on macOS and Linux, follow [administrator commands](administrator-commands.md).

Follow [setup responsibilities](setup-responsibilities.md) for every step.

Choose one complete ordered procedure. Each covers account and network
preparation, capability/secret registration, tooling and operator sign-in,
desktop control, saving and proving a restorable baseline, and recovery.
Each numbered step carries named-machine/date audit evidence or an explicit
unverified label; code-reviewed contracts do not substitute for live proof.

- [macOS](macos-host-provisioning.md)
- [Linux](linux-host-provisioning.md)
- [Windows with WSL2](windows-host-provisioning.md)

Hostnames, account names, infrastructure and credentials are project-owned.
Installed Pack files belong to the project; immutable catalog versions retain
historical distribution content. [README](README.md) describes the QA methods.

Baseline restores clear test-account-owned Yoke, Playwright, Chromium and pip
run artifacts from system and OS user temporary locations, preserving the
golden directory and sidecars, live browser identity store and restored home.
The receipt reports removed entries and `temp_cleanup.freed_bytes`. Reset and
verify refuse `test_machine_cleanup_live_lease` while a mission owns the host;
finish or abort it before resetting. Every mission requires 1 GiB free on the
home and temporary filesystems before packages or scratch are staged.
`test_machine_disk_space_low` records the minimum and observed space; finish
or abort the mission, run `yoke test-machine reset --project P --machine NAME`,
and grow the disk as in [disk sizing and online resize](#disk-sizing-and-online-resize)
if reset cannot recover the required space. Read reset `--help` before running it.

A failed native request keeps its diagnosed reason and recovery. Quota waits for
provider capacity, transport waits for service recovery, and authentication
advice requires native auth evidence. Unknown nonzero failures need local
diagnostics. Preserve the failed capture and golden; a failure never seals.

## Disk sizing and online resize

Give every macOS and Linux Test Machine at least 40 GiB on the volume that
holds the test home and temporary directories. That space holds the OS,
desktop and Chromium, a 3-4 GiB test home, one golden, a second home-sized
copy while a golden is captured, harness installs, mission scratch and the
1 GiB mission admission floor. A 20 GiB Linux root filled repeatedly.

Check usage, then grow online without a reboot. Linux on AWS, as administrator
of the account that owns the volume, then on the host:

```text
yoke test-machine exec --project P --machine NAME -- df -h / /tmp
aws ec2 modify-volume --volume-id VOLUME_ID --size 40
aws ec2 describe-volumes-modifications --volume-ids VOLUME_ID
yoke test-machine exec --project P --machine NAME --admin -- growpart /dev/nvme0n1 1
yoke test-machine exec --project P --machine NAME --admin -- resize2fs /dev/nvme0n1p1
```

Wait for the modification state `optimizing` or `completed` before
`growpart`. Read the device and partition from `lsblk`; use
`xfs_growfs /` instead of `resize2fs` on XFS. Declare the new size in the
project's IaC or record it as an explicit operator exception.

An EC2 Mac grows the same way after `modify-volume`; then, with the disk and
APFS container read from `diskutil list physical external`:

```text
yoke test-machine exec --project P --machine NAME --admin -- sh -c 'yes | diskutil repairDisk DISK'
yoke test-machine exec --project P --machine NAME --admin -- diskutil apfs resizeContainer CONTAINER 0
```

`yes` answers the `repairDisk` confirmation. A physical Mac's internal disk
cannot grow: free space with reset and old-golden retention, or move to a
larger machine. Confirm with `df -h` and rerun the refused QA.
