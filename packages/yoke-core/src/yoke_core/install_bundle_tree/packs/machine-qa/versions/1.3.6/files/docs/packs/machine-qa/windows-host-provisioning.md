# Provisioning a persistent Windows WSL2 Test Machine

Declare `os=windows`; SSH reaches Windows OpenSSH and test operations run
through `wsl.exe --cd ~ -e /bin/bash -lc` in that account's default WSL2 distro,
starting in the Linux home instead of the Windows SSH directory.
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
restart. When stable access across Spot restarts is operator-approved,
associate an Elastic IP and retain it across stops; its address charge
continues while compute is stopped.

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
Sign in Claude, Codex and Cursor as that WSL user and prove a real request
from each. Have the operator accept Claude's one-time dangerous-mode bypass
warning there; the standard check reads `skipDangerousModePermissionPrompt`
without writing it or accepting the warning. Windows credentials, desktop
state and WSL registration are outside the saved Linux home.
WSL's distro lifecycle can stop background daemons when its last Windows
client exits. Keep a WSL terminal open while testing the local universe/UI;
after a distro restart, `yoke init --local` restarts its Postgres authority.
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
The adapter streams long Linux programs over SSH stdin, keeping Windows command
text bounded and preserving the program's original stdin for golden operations.
Capture defaults to real-request and bypass-acceptance checks for the WSL user;
status text alone is insufficient. Remove Yoke installation/session residue
before capture, retaining signed-in harnesses and remote-access credentials.
The Linux XFCE/xrdp session-start recipe is unverified for WSL and does not
establish a native Windows session. Provision that desktop separately below.

```text
yoke test-machine golden-capture --project P --machine NAME --destination /var/lib/yoke-golden/yoketest/home
yoke test-machine reset --project P --machine NAME --baseline fresh-host
yoke test-machine verify --project P --machine NAME
yoke test-machine exec --project P --machine NAME -- uname -a
```

Registered terminal QA uses tmux transcripts. Desktop screenshot proof uses
`yoke test-machine screenshot --project P --machine NAME --json`. Provision
FreeRDP's SDL command-line client on the credential-owning execution workstation:
macOS uses `brew install freerdp` and `sdl-freerdp`; Linux uses its distribution's
SDL FreeRDP package providing `sdl-freerdp` or `sdl-freerdp3`. No X server is
required by the SDL client. FreeRDP 3.32.1 and these flags were checked on the
macOS execution workstation on 2026-10-02. A registered Windows Server machine
proved auth-only, reuse and automatic startup with an unlocked 1280×800 PNG on
that workstation. The Linux execution package remains unverified.

Register the Windows SSH account as `desktop_user` too, an RDP `desktop_protocol`,
and the existing `desktop_route`/`desktop_port`; prefer `ssh-forward`, with RDP
reachable only through SSH. Import `test-machine:NAME.desktop_password` through
`yoke projects capability secret set --value-file FILE` or `--value-stdin`,
with its required project, capability type and key flags. The password stays in
that capability secret store. A GUI operation reuses an active registered login
or starts and holds FreeRDP through its SSH forward until capture finishes.
The receipt reports `desktop_session=started|reused`. Another user's active
login refuses instead of being displaced. No Windows auto-logon or host-side
configuration change is made. The product feeds the password on stdin via
`/from-stdin:force`, never in argv, output, events or a temporary password file.

`yoke test-machine desktop-access --project P --machine NAME` proves the
registered credential with FreeRDP `+auth-only`, reports authenticated proof,
and closes its forward without creating a desktop session. Missing FreeRDP
refuses as `windows_rdp_client_missing`, naming installation and a human RDP
login kept open as the fallback; it never waits indefinitely for a client.

WSL2 invokes Windows PowerShell and a temporary task using the SSH account's
held interactive token. The task captures the primary Windows display,
returns a PNG to the QA artifact store, and removes itself and its files.
No password enters that task. Session 0, locked desktops and blank images
refuse with a named recovery rather than earning screenshot credit.
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

### Standard capture checks

- `Claude real request`, `Codex real request`, `Cursor real request`: each WSL CLI answers.
- `Claude bypass accepted`: the operator accepted its one-time warning in WSL.

A supplied probe document must include every name above; missing names refuse
as `baseline_standard_probes_missing`. Start from the current `.probes` sidecar
for extra checks. Capture always runs/seals canonical standard programs plus
the extras; it never carries an older sidecar forward implicitly. A failed
standard check names the provisioning repair and cannot register a new golden.
Harness output stays on the host. Require the checks to pass after the reset
roundtrip, and keep capture, reset and verify receipts.
