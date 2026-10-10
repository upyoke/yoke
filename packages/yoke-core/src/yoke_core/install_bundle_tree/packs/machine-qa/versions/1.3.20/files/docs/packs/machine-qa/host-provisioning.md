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
and expand the disk if reset cannot recover the required space. Read reset
`--help` before running it.
