# Provisioning a persistent Windows WSL2 Test Machine

Declare `os=windows`; SSH reaches Windows OpenSSH and test operations run
through `wsl.exe -e /bin/bash -lc` in that account's default WSL2 distro.
The SSH account is a Windows account; the Linux default user must be non-root.
Use Ubuntu 24.04, systemd and tmux, following the
[Linux tooling, sign-in and golden instructions](linux-host-provisioning.md).
This tests Linux inside WSL; it does not install native Windows Yoke.

## Host and access

Use the project's infrastructure declaration or record an explicit operator
exception before provisioning. An AWS Windows Server 2025 Full Base host
needs a supported instance such as `m8i.large` with
`CpuOptions.NestedVirtualization=enabled`; the family alone is insufficient.
Persistent Spot with interruption behavior `stop` preserves the test home.
Query current Windows license-included compute/Spot and EBS prices and obey
the cost gate before launching. Stop whenever not testing. An automatically
assigned public IPv4 releases on stop; update the capability host after
restart. Avoid retaining a billable Elastic IP.

Start Windows OpenSSH `sshd` automatically, authorize the shared test-machine
public key, disable password authentication and restrict inbound SSH to the
execution machines. Administrator accounts use
`%ProgramData%\ssh\administrators_authorized_keys`, accessible only to
Administrators/SYSTEM. Private keys never belong in user data or evidence.
WSL distros are per Windows user: install under the SSH account, not an
unrelated system service account.
Check the active network profile: the default OpenSSH rule can be Private-only
on a Public-profile EC2 interface. Set that rule's profile to `Any` while
keeping the AWS security group's source-IP restriction.

## WSL2 and the Linux home

In elevated PowerShell enable `Microsoft-Windows-Subsystem-Linux` and
`VirtualMachinePlatform`, run `wsl --install --no-distribution --web-download`,
then reboot. Under the SSH account install Ubuntu 24.04, set it as default,
and prove version 2 with `wsl --list --verbose`. Create the non-root Linux
test user and set `/etc/wsl.conf` inside Ubuntu:

```ini
[boot]
systemd=true
[user]
default=yoketest
```

Restart WSL with `wsl --shutdown`. Prove `wsl -e id -u` is nonzero and
systemd runs. Install the Linux prerequisites and harness CLIs in that home;
perform vendor sign-in through documented operator paths.
If native installation under a service account reports WSL absent, use
Microsoft's [offline MSI installation](https://learn.microsoft.com/en-us/windows/wsl/install#offline-install)
with its published digest, then install the distro under the SSH account.

Give the test user passwordless sudo for automatic privileged library setup:
write `yoketest ALL=(ALL) NOPASSWD: ALL` to
`/etc/sudoers.d/yoke-test-user`, set mode `0440`, and validate both `visudo -c`
and `sudo -n true` as the user. Include that system prerequisite in the host
baseline contract. Full onboarding, including browser QA, must pass.

## Golden and verification

The golden is an absolute **Linux** path outside the Linux home, for example
`/var/lib/yoke-golden/yoketest/home`. Windows state, SSH access and distro
registration survive reset. The existing Linux archive, digest, owner, probes
and absence gates apply.

```text
yoke test-machine golden-capture --project P --machine NAME --destination /var/lib/yoke-golden/yoketest/home --probes-file probes.json
yoke test-machine verify --project P --machine NAME
yoke test-machine exec --project P --machine NAME -- uname -a
yoke test-machine reset --project P --machine NAME --baseline fresh-host
```

Registered terminal QA uses tmux transcripts. Screenshot/GUI methods retain
the Linux designed deferral; a transcript does not prove a desktop window.
For separate WSLg checks, prove `/mnt/wslg`, its Wayland socket and an
interactive Windows desktop, then launch Linux desktop apps inside WSL and
inspect their registered Linux sessions. A WSLg version number alone does
not prove rendering. Windows Server and Windows 11 behavior need separate
evidence; Microsoft's [GUI prerequisites](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps)
name Windows 10/11. Report missing Server WSLg before changing images.

Serve the Yoke UI inside WSL and open its localhost URL in the Windows browser.
Record whether ordinary NAT localhost forwarding suffices. Probe the actual
host before claiming mirrored networking is required or supported.
When Python's opener fails, Yoke tries `wslview`, then `explorer.exe`; install
`wslu` or enable Windows interop/PATH if both are missing.
