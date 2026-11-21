# Provisioning and saving a Linux Test Machine

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > Linux host provisioning
<!-- /yoke:breadcrumbs -->

Follow the [normal-user installation rule](index.md#install-as-the-test-user).

For stored-password setup commands on macOS and Linux, follow [administrator commands](administrator-commands.md).
Follow [setup responsibilities](setup-responsibilities.md) and the project-owned
manual preparation inventory in the [provisioning index](host-provisioning.md).
[Codex on Linux](codex-on-linux.md) covers scoped posture and helper recovery.

Follow this ordered procedure as a dedicated non-root test user, from a bare
Ubuntu 24.04 host through a verified saved state. Infrastructure, account,
endpoint, project slug, passwords and baseline paths remain project-owned.

## 1. Host, tools and account

Declare cloud resources through project IaC, or record an explicit operator
exception before provisioning. Use Ubuntu 24.04, a root volume of at least
40 GiB ([disk sizing](host-provisioning.md#disk-sizing-and-online-resize)),
a 4 GiB instance (8 GiB recommended), at least 2 GiB swap, and one
dedicated non-root user. Kernel reservations reduce nominal RAM; verify requires
3.5 GiB usable RAM (3758096384 bytes). It refuses test_machine_memory_below_minimum
with observed and required bytes before reset. A 1 GiB host cannot leave the
native launch minimum of 1 GiB available. Resize first; swap does not replace
RAM. The administrator installs base tools and creates that account:

```text
sudo apt-get update
sudo apt-get install -y ca-certificates curl git tmux python3 python3-venv nodejs npm
sudo adduser --disabled-password --gecos '' TESTUSER
sudo install -d -m 0700 -o TESTUSER -g TESTUSER /var/lib/yoke-golden/TESTUSER
```

Complete the project's manual runtime preparation, including service/group
readiness and real containers/Compose v2 when Docker is declared. This rig needs
passwordless sudo for Chromium library setup, independently of runtime access. As the
administrator, prepare a drop-in substituting the actual test account:

```text
printf '%s\n' 'TESTUSER ALL=(ALL) NOPASSWD: ALL' > /tmp/yoke-test-user.sudoers
sudo visudo -c -f /tmp/yoke-test-user.sudoers
sudo install -o root -g root -m 0440 /tmp/yoke-test-user.sudoers /etc/sudoers.d/yoke-test-user
sudo visudo -c
sudo -u TESTUSER sudo -n true
```

Require a nonzero `id -u`, Ubuntu24.04 in `/etc/os-release`, and working
`git --version`, `tmux -V`, `python3 --version`, `sudo -n true` and the
project-declared runtime workload checks
as the user. System packages, services and sudo policy are outside the home
golden. Do not record QA package changes as the permanent machine baseline.

### Codex sandbox namespace access

Ubuntu24.04 restricts unprivileged user namespaces by default. Keep
`kernel.apparmor_restrict_unprivileged_userns=1`. If a harmless command in the
Codex session opened through the desktop fails before execution with
`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`, inspect fresh
kernel audit events as administrator:

```text
sudo journalctl -k --since '10 minutes ago' --no-pager -g 'apparmor.*(bwrap|userns|codex)'
```

Read the bwrap executable path from the denied userns/capability event. Do
not infer it from PATH or the npm launcher: Codex may use its app-server
daemon. Install bubblewrap only if the actual required helper is missing.
Preserve existing profiles; grant userns only to the exact audited executable.
For an app-server helper, create `/etc/apparmor.d/codex-bwrap` with:

```text
abi <abi/4.0>,
include <tunables/global>
profile codex_bwrap "/home/user/.codex/packages/app-server-daemon/releases/INSTALLED_RELEASE/codex-resources/bwrap" flags=(unconfined) {
  userns,
  include if exists <local/codex-bwrap>
}
```

Replace the entire quoted path with the actual audited absolute executable;
TESTUSER and INSTALLED_RELEASE are placeholders, never a copied version.
Load with `sudo apparmor_parser -r /etc/apparmor.d/codex-bwrap`, then check:

```text
sysctl kernel.apparmor_restrict_unprivileged_userns
sudo aa-status
```

Require the global sysctl still1 and `codex_bwrap` loaded. In the SAME desktop-opened Codex
session, request a harmless normal sandboxed pwd/printf command. Require
actual exit code 0 and output, then inspect fresh audit events for renewed
namespace/capability denial. Do not escalate the probe, change Codex
permissions, disable the global sysctl, reset the host, or accept model text
as execution proof. Re-audit the helper path after Codex updates. A new
denial or unavailable helper is a provisioning blocker; stop and report it.

### Join Tailscale before registration

Follow [tailnet bootstrap](tailnet-bootstrap.md) for provider start, current-IP
SSH, stable lab naming and operator sign-in approval before these OS checks.

Install Tailscale on the host and join the operator's tailnet by completing its
sign-in flow. Enable startup/unattended operation and disable device key expiry
in the admin console. Controllers join the same tailnet and use MagicDNS.
This is one-time manual machine setup.

Use the [Linux installer](https://tailscale.com/download/linux), enable the
`tailscaled` service (`sudo systemctl enable --now tailscaled`) and run
`sudo tailscale up --hostname=LAB_NAME`; give its sign-in URL to the operator.

Read `Self.DNSName` from `tailscale status --json`, trim the trailing dot and
resolve that exact MagicDNS name from the controller. Prove OpenSSH key login,
then register it as `host`; the direct desktop route uses that name too.
For cloud bootstrap, query the provider's **current** public IP and connect with
the [bootstrap SSH command](tailnet-bootstrap.md#start-the-lab-and-reach-its-current-address);
never register that IP.
Keep key-only internet SSH open from anywhere; desktops stay on the tailnet.
EC2 uses auto-assigned public IPv4 while running, with no Elastic IP.
Power starts by instance id and waits for SSH on the registered MagicDNS name.
Cloud hosts stay running after lease release. See the
[manual stop commands](host-provisioning.md#stop-a-cloud-test-machine) for
operator shutdown. Golden reset never touches Tailscale.

Before rebuilding, remove the old tailnet device first, then join the replacement
with the same hostname; verify no `-1` suffix. Verify the new SSH fingerprint,
then clear the old cloud instance-id pin using
`ssh-keygen -R INSTANCE_ID -f KNOWN_HOSTS` in Yoke's Test Machine known_hosts file
(physical hosts use the hostname pin). Re-read settings and use the as-read token
with `settings-replace` for any change, then run `yoke test-machine verify`.
If DNS/SSH fails, check Tailscale startup, device expiry, controller DNS and sshd;
never fix reachability by changing the target while its lease is active.

Existing public-IP registrations: join first, deploy the no-rebind build second,
then settings-replace `host` with MagicDNS using the as-read token. Upgrading
clients prevents old calls to the retired rebind function. Verify across a power
cycle and require the same host with no remaining QA_HOST afterward.

## 2. SSH, capability and desktop access

Authorize the project's shared public SSH key in the test account's
`~/.ssh/authorized_keys` (directory0700, file0600, both test-user-owned).
Disable password/keyboard-interactive SSH; retain public-key access. Open SSH
to any address and keep RDP off public networks, as
[network access](host-provisioning.md#network-access) requires; audit the
effective SSH and firewall policy, not just successful login.

Register with `yoke test-machine settings-replace --test-machine NAME --settings-file FILE --new`.
Declare `resource_name`, `os=linux`, `host`, `user` and a golden path outside the
home. For updates use the as-read settings token. Add `cloud_instance_id` if
a lease should start the host. Its MagicDNS address stays the same. Verify
after setting [capability tags](host-provisioning.md#register-capability-tags).
Register launch capacity separately under another home.

On each QA workstation, store shared SSH and per-host desktop secrets:

```text
yoke test-machine secret set --test-machine NAME --key ssh_private_key --value-file KEY_FILE
yoke test-machine secret set --test-machine NAME --key desktop_password --value-file PASSWORD_FILE
yoke test-machine exec --test-machine NAME -- /usr/bin/true
```

Read each command's `--help`. Private bytes never enter settings, argv, logs,
artifacts or source. `exec` uses the workstation's SSH agent; host operations
resolve per-machine secrets. A serial host lease held by another session
requires waiting before preparation/access.

After step4, declare `desktop_protocol=rdp`, `desktop_route=direct`,
`desktop_port=3389`, `desktop_user=TESTUSER` with no `desktop_host`, so the
desktop is the registered MagicDNS host. A host outside the tailnet declares
`desktop_route=ssh-forward` instead; its default desktop host is remote loopback.
Operator access uses `yoke test-machine desktop-access --test-machine NAME`; read `--help`. Open its returned address in an RDP
client, no gateway, Xorg session, with the registered test user and password
from the private `password_file`; on the direct route compare the printed
`certificate_sha256` with the certificate your client shows. An SSH-forward
address works while the command runs; press Enter to close it. Remove only the
temporary password copy. For an announced personal sign-in handoff with a
visible FreeRDP SDL viewer, add `--view`; the product supplies the password on
stdin and closes any forward with the viewer.
Read `--help` for the required client. Agent captures prove test rendering.

## 3. Harness installation and sign-in

Use each vendor's supported installer as the test user, with `.local/bin` on
login and SSH PATH. These commands are provisioning actions, not audit probes:

```text
curl -fsSL https://claude.ai/install.sh -o /tmp/claude-install
bash /tmp/claude-install
curl -fsSL https://chatgpt.com/codex/install.sh -o /tmp/codex-install
sh /tmp/codex-install
curl -fsSL https://cursor.com/install -o /tmp/cursor-install
bash /tmp/cursor-install
```

Check current [Claude requirements](https://code.claude.com/docs/en/setup),
[Codex installation](https://developers.openai.com/codex/cli) and
[Cursor installation](https://cursor.com/docs/cli/installation) before use;
a distribution's old Node package is not proof of supported vendor runtime.
Record actual executable paths in the fixture. Golden capture records each CLI's version beside the golden in
`GOLDEN.harness-clis`. Before a QA plan's first reset on this host, Yoke
compares those versions with each vendor's latest release; when one is newer
it resets, installs the newer CLIs with each vendor's installer as the test user and
captures a new golden under the plan's own host lease. Do not hand-update
CLIs for QA; a failed refresh stops the plan with the step to repair.

Use the test user's terminal/tmux session and the [browser identity procedure](#5-optional-live-browser-identities):
Claude's documented login flow (`claude`, `/login`); Codex
`codex login --device-auth` when the [account/workspace permits it](https://developers.openai.com/codex/auth);
Cursor `NO_OPEN_BROWSER=1 agent login` and its printed URL
([authentication](https://cursor.com/docs/cli/reference/authentication)).
Installed Cursor may also expose `cursor-agent`. Apply that same authorization
procedure to the native login URL; keep credentials on the host.

Require a real request from each harness, not status text or a credential-file
count. Once per machine, accept Claude's dangerous-mode prompt
in the dedicated test context; require `skipDangerousModePermissionPrompt=true`
before saving. It is signed-in home state restored from the golden, not a
permission to bypass unrelated product safeguards.

Keep every harness installation and sign-in live outside the golden; follow
[Linux live-state preservation and reset recovery](linux-live-state.md).
Require all three real requests before reset. Every Chromium is asked to quit
so the identity store `~/.yoke-browser-identities` is flushed; reset keeps that
store live, never an older golden copy. Require separate reset and browser
sign-in proof in the [baseline procedure](linux-baseline-recovery.md).

## 4. Durable desktop and unattended sessions

For desktop coverage, the executing product operation runs this stdlib-only
core helper as the dedicated test user, with private capability input. Copy
`yoke_harness/host_provisioning/provision_linux_desktop.py` from the controller's
Yoke package into the target working directory before running:

```text
python3 provision_linux_desktop.py --desktop-password-stdin --browser-project P --browser-identity NAME
python3 provision_linux_desktop.py --verify
```

Provisioning requires `--browser-project` and `--browser-identity`, naming the
operator identity (the project's browser-control `default_identity`);
`--verify` takes neither. It requires Ubuntu24.04 and passwordless sudo,
installs XFCE, xfce4-terminal, xfce4-helpers, xdg-utils, GTK's launcher tools,
xorgxrdp/xrdp, dbus-x11, scrot, xdotool, nftables and venv support. It refuses
another `.xsession` choice and proves active services. xrdp listens on every
interface, and a persisted nftables table (`yoke-desktop-firewall.service`,
loaded before xrdp) drops RDP arriving anywhere but `lo` and `tailscale0`;
`--verify` proves both. It sets
`TerminalEmulator=xfce4-terminal` and `WebBrowser=yoke-identity-browser` in
`~/.config/xfce4/helpers.rc`, preserving unrelated helpers. The XFCE browser
helper uses `gtk-launch` to open the existing identity launcher
`~/.local/share/applications/yoke-identity-browser.desktop`. The launcher runs
`yoke browser open --project P --identity NAME` through a login shell and is
also the HTTP, HTTPS, and HTML default in `~/.config/mimeapps.list`.
`--verify` checks the helper packages, both XFCE selections, the browser
helper, and the MIME defaults. It refuses a missing browser configuration as
`linux_desktop_default_browser_not_selected`. Capture the provisioned home
in the golden so resets restore its launcher and browser settings.
Once Yoke is installed and the identity authorized, confirm in the XFCE
session that `exo-open --launch TerminalEmulator` opens a terminal and
`xdg-open https://example.com` opens the page in the identity's Chromium.
An existing customization requires an operator decision before provisioning.
Tools/services are system baseline; session selection is captured home state.
Do not install scrot/xdotool as a mission-journaled package delta: another reset
can reverse that journal. Current terminal selection is retained by reset.

Provisioning requires the operation to stream the capability-owned
`desktop_password` on private stdin. It sets the dedicated fixture user's
local password with `sudo -n chpasswd`. The next registered GUI operation reuses
the product's existing uploaded desktop helper and owned-session startup; the
host needs no harness-package import. The operator never types sudo, sets a machine
password or logs into the desktop. No secret enters a file, argv or output;
SSH stays key-only and PAM stays enabled. `--verify` checks readiness only and
refuses the password flag. Provisioning itself reports `desktop_session=not_started`.

Screenshot, GUI commands and desktop access start or reuse one dedicated XFCE
session. Multiple sessions refuse as ambiguous. Capture waits for a nonblank
frame and reports whether the desktop started or was reused.

Unattended startup uses `xrdp-sesrun -s ::1 -t Xorg -F 0 -g 1920x1080 TESTUSER`
with the fixture password on stdin. Keep `-s ::1` for sesman on `[::1]:3350`.
If startup refuses, repair the named prerequisite and retry. Use human RDP
login only for cases that explicitly test it.

For XTEST input on the actual leased display, use xdotool without `--window`;
delivery through the focused window needs several seconds before being judged
undelivered. The registered GUI-session route selects DISPLAY, XAUTHORITY and
D-Bus from the test user's actual XFCE session; a dummy display is not proof.
Prove the visible result and screenshot with `yoke test-machine screenshot --test-machine NAME --json`; read `--help`. Transcripts alone do not
prove the desktop. Reset ends the registered fixture user's desktop, including a session reused
from a human login. It verifies process identity before termination and proves
that the desktop ended; other users' sessions are excluded.
Prove unattended start after a fresh-host reset, then prove reuse with a second
capture of the same display. Reset performs fixture desktop logout itself.

## 5. Optional live browser identities

Follow [Linux browser identities](linux-browser-identities.md) for sign-in
and approval gates.

## 6. Capture, reset and recovery

Continue with [Linux baseline capture and recovery](linux-baseline-recovery.md).
Complete its standard probes, save/reset roundtrip and final clean signed-in
baseline before reporting the host ready. Its recovery table preserves the
named refusal and sealed-state repair for a failed operation.

Cloud SSH routes use `HostKeyAlias=<cloud_instance_id>` instead of an IP pin.
The first connection accepts the instance key once with `accept-new`; later
address changes keep that identity. If the instance is rebuilt, verify its new
key, then remove the old alias with `ssh-keygen -R INSTANCE_ID -f KNOWN_HOSTS`
from the Yoke-managed Test Machine known_hosts file before reconnecting.
