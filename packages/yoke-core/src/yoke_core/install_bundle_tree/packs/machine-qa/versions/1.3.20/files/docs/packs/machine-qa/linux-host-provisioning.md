# Provisioning and saving a Linux Test Machine

For stored-password setup commands on macOS and Linux, follow [administrator commands](administrator-commands.md).

Follow [setup responsibilities](setup-responsibilities.md) for every step.

Follow this ordered procedure as a dedicated non-root test user, from a bare
Ubuntu 24.04 host through a verified saved state. Infrastructure, account,
endpoint, project slug, passwords and baseline paths remain project-owned.

## 1. Host, tools and account

Declare cloud resources through project IaC, or record an explicit operator
exception before provisioning. Use Ubuntu 24.04 and one dedicated non-root
user. The administrator installs base tools and creates that account:

```text
sudo apt-get update
sudo apt-get install -y ca-certificates curl git tmux python3 python3-venv nodejs npm docker.io
sudo systemctl enable --now docker
sudo adduser --disabled-password --gecos '' TESTUSER
sudo usermod -aG docker TESTUSER
sudo install -d -m 0700 -o TESTUSER -g TESTUSER /var/lib/yoke-golden/TESTUSER
```

Log in again after group changes. This dedicated rig needs passwordless sudo
for automatic Chromium library setup, not just Docker-group access. As the
administrator, prepare a drop-in substituting the actual test account:

```text
printf '%s\n' 'TESTUSER ALL=(ALL) NOPASSWD: ALL' > /tmp/yoke-test-user.sudoers
sudo visudo -c -f /tmp/yoke-test-user.sudoers
sudo install -o root -g root -m 0440 /tmp/yoke-test-user.sudoers /etc/sudoers.d/yoke-test-user
sudo visudo -c
sudo -u TESTUSER sudo -n true
```

Require a nonzero `id -u`, Ubuntu24.04 in `/etc/os-release`, and working
`git --version`, `tmux -V`, `python3 --version`, `docker info`, `sudo -n true`
as the user. System packages, services and sudo policy are outside the home
golden. Do not record QA package changes as the permanent machine baseline.

## 2. SSH, capability and desktop access

Authorize the project's shared public SSH key in the test account's
`~/.ssh/authorized_keys` (directory0700, file0600, both test-user-owned).
Disable password/keyboard-interactive SSH; retain public-key access. Restrict
network ingress to approved execution machines; audit the effective SSH and
firewall policy, not just successful login.

Register `test-machine:<name>` through `yoke test-machine settings-replace
--project P --machine NAME --settings-file FILE --new`. Read `--help`; updates
use the as-read settings token. Settings include `resource_name`, `os=linux`,
`host`, `user` and the absolute home golden path outside the home. A cloud
instance id and operating notes belong to this record, not Pack source.
A capacity machine is independent; ordinary agent work must use another home.

On each QA workstation, store shared SSH and per-host desktop secrets:

```text
yoke projects capability secret set --project P --cap-type test-machine --key ssh_private_key --value-file KEY_FILE
yoke projects capability secret set --project P --cap-type test-machine:NAME --key desktop_password --value-file PASSWORD_FILE
yoke test-machine exec --project P --machine NAME -- /usr/bin/true
```

Read each command's `--help`. Private bytes never enter settings, argv, logs,
artifacts or source. `exec` uses the workstation's SSH agent; host operations
resolve capability secrets. A serial host lease held by another session
requires waiting before preparation/access.

After step4, declare `desktop_protocol=rdp`, `desktop_route=ssh-forward`,
`desktop_port=3389`, `desktop_user=TESTUSER`; the default forwarded desktop host
is remote loopback. Operator access uses `yoke test-machine desktop-access
--project P --machine NAME`; read `--help`. Open its returned loopback address
in an RDP client, no gateway, Xorg session, with the registered test user and
password from the private `password_file`. Close its tunnel after use with
`ssh -F /dev/null -S PASSWORD_FILE.ssh -O exit SSH_USER@SSH_HOST`; remove only
its temporary password copy. No public RDP ingress is needed. For an announced
personal sign-in handoff with a visible FreeRDP SDL viewer, add `--view`; the
product supplies the password on stdin and closes its forward with the viewer.
Read `--help` for the required client. Agent captures prove test rendering.

## 3. Harness installation and operator sign-in

Use each vendor's supported installer as the test user, with `.local/bin` on
login and SSH PATH. These commands are provisioning actions, not audit probes:

```text
curl -fsSL https://claude.ai/install.sh -o /tmp/claude-install
bash /tmp/claude-install
npm install --global --prefix "$HOME/.local" @openai/codex
curl -fsSL https://cursor.com/install -o /tmp/cursor-install
bash /tmp/cursor-install
```

Check current [Claude requirements](https://code.claude.com/docs/en/setup),
[Codex installation](https://developers.openai.com/codex/cli) and
[Cursor installation](https://cursor.com/docs/cli/installation) before use;
a distribution's old Node package is not proof of supported vendor runtime.
Record installed CLI versions and actual executable paths in the fixture.

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

## 4. Durable desktop and unattended sessions

For desktop coverage, the executing product operation runs this stdlib-only
Pack helper as the dedicated test user, with private capability input:

```text
python3 ops/machine-qa/provision_linux_desktop.py --desktop-password-stdin
python3 ops/machine-qa/provision_linux_desktop.py --verify
```

It requires Ubuntu24.04 and passwordless sudo, installs XFCE, xfce4-terminal,
xorgxrdp/xrdp, dbus-x11, scrot, xdotool and venv support, refuses another
`.xsession` choice, and proves active services and loopback-only RDP. It sets
`TerminalEmulator=xfce4-terminal` while preserving other helpers.rc choices.
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

The serving build's registered Linux screenshot, GUI-session execution and
desktop-access operations start or reuse the dedicated XFCE session. Their
receipt states `desktop_session=started|reused`. Exactly one existing human
XFCE desktop may be reused; multiple desktops refuse as ambiguous. The first
capture waits for a valid nonblank frame while retaining `started` evidence;
an already running desktop with a blank capture still refuses.
The unattended route uses `xrdp-sesrun -s ::1 -t Xorg -F 0 TESTUSER`, feeding
the registered password on stdin. On a host whose sesman listens on
`[::1]:3350`, omitting `-s ::1` can report a connect error. Do not run a
password-bearing workaround. If the operation refuses sesrun/startup, repair
its named prerequisite and rerun. Human RDP login is used only by cases that
explicitly test human login.

For XTEST input on the actual leased display, use xdotool without `--window`;
delivery through the focused window needs several seconds before being judged
undelivered. The registered GUI-session route selects DISPLAY, XAUTHORITY and
D-Bus from the test user's actual XFCE session; a dummy display is not proof.
Prove the visible result and screenshot with `yoke test-machine screenshot
--project P --machine NAME --json`; read `--help`. Transcripts alone do not
prove the desktop. Reset ends the registered fixture user's desktop, including a session reused
from a human login. It verifies process identity before termination and proves
that the desktop ended; other users' sessions are excluded.
Prove unattended start after a fresh-host reset, then prove reuse with a second
capture of the same display. Reset performs fixture desktop logout itself.

## 5. Optional live browser identities

A test machine keeps each project identity signed in live, outside the
clean-home golden.

1. As the test user, create the live identity store once:
   `mkdir -m 700 ~/.yoke-browser-identities`. Never place it inside `~/.yoke`.
   A full reset keeps it the way it keeps harness logins, and golden capture
   never includes it, because a restored copy of a session is the cookies the
   site has since rotated.
2. Agents use the registered test user and leased product operations to install
   the candidate and prepare its Chromium runtime and real headed desktop.
   Declare the project's identities and each identity's per-site sign-in
   checks in its `browser-control` capability settings; see
   [browser identities](browser-identities.md).
3. For each identity, agents run `yoke browser authorize --project P
   --identity NAME` as the test user in the real headed desktop; read
   `--help`. It checks every declared site first and opens a window only for
   the expired ones, naming the identity, the site and the account; no
   automated browser runs while it is open. The user supplies personal
   credentials. Follow the existing [test-account approval rule](https://github.com/upyoke/yoke/blob/main/docs/testing-verification/test-machine-golden-baseline.md#yoke-application-sign-ins)
   for the agent/user split, including native harness login from this saved
   session. Keep profile data on the host.
4. The user closes every authorization window; the command checks each site
   again and fails naming any still signed out. The identity's profile path
   links into the store, so the sign-in already lives there: nothing is
   captured, sealed or restored.
5. A reset removes `~/.yoke` and keeps the store. Once a walk installs the
   candidate, `yoke browser verify --project P --identity NAME` proves each
   site still signed in, and sessions a site refreshes during the walk persist
   in the store whether the walk passes, fails or is aborted.
6. Agents perform application steps that do not need the user. An expired site
   is a precise `HUMAN_GATE` naming the machine, identity, site, account and
   resume state; the resume is `yoke browser authorize --identity NAME` on that
   host. Runtime and inventory failures retain their named diagnostics.

The real headed session comes from the registered XFCE desktop route in
step 4, never a dummy display.

## 6. Clean home, standard checks and capture

If a current golden exists, reset to it before refreshing signed-in fixture
state. If step5 temporarily installed Yoke, return to the clean existing
baseline after sealing the separate profile. For a first bare home, keep Yoke
absent before saving; registering/capture runs from the QA workstation.
Do not manually capture a partially cleared home or bake Yoke/uv state into it.

Acceptance requires steps1–4 plus all native harness real requests, Claude
bypass acceptance, and a startable desktop/input tools when desktop coverage
is configured. Golden capture selects standard per-OS probes without a file;
a custom probes JSON must include every standard check. Read the command's
served `--help` for argv rules. Standard names are `Claude real request`,
`Codex real request`, `Cursor real request`, `Claude bypass accepted`, and
`Linux desktop input available` (headless hosts pass without xdotool).
Missing names refuse as `baseline_standard_probes_missing`. Capture runs and
seals canonical standard programs plus extras, without implicitly carrying an
older sidecar forward. Extra probes use absolute argv and
positive expectations; an exit-zero `agent status` is not authenticated proof.
Named harness probes are executed as tiny real requests without tool calls.

Capture into a new absolute directory outside the test home:

```text
yoke test-machine golden-capture --project P --machine NAME --destination /var/lib/yoke-golden/TESTUSER/home-DATE
```

The default is a new dated sibling of the current golden. Failure never
replaces the registered baseline. The directory contains private `home.tar.gz`
and `manifest.json` binding archive digest, UID and home; sealed probe state
travels beside the golden. Capture omits sockets and links to sockets/outside
the home, retaining regular `.sock` files and safe persistent CLI links.
Live `.ssh` and the browser identity store `.yoke-browser-identities` are
never captured and are preserved on restore. No archive or auth material enters QA
artifacts, settings or source control.

## 7. Prove the save/reset roundtrip

Golden capture restores the new archive and re-runs its sealed probes before
registration. It then uses the existing xrdp login to start the fixture desktop,
captures a non-blank first frame, and ends the desktop session. A failure names
`reset_roundtrip`, `restored_probes`, `desktop_frame`, or `desktop_end` and refuses
to register the capture; repair that step and capture to a new destination.
Reset ends an open fixture desktop rather than requiring manual logout.

These are destructive provisioning commands, not read-only reachability checks:

```text
yoke test-machine verify --project P --machine NAME
yoke test-machine reset --project P --machine NAME --baseline fresh-host
yoke test-machine get --project P --machine NAME
```

Read `--help`. Verify reaches both baselines and leaves `shell-preconfigured`
with the current launcher installed. The final reset reaches only the clean,
signed-in `fresh-host`. Require passing receipts bound to the new golden,
standard request checks, desktop startup and input tools after restore.
Browser UI proof requires the separate restoration in step5.

Reset validates archive identity/digest/entries before clearing, removes owned
product services and home writers, restores files/modes and proves Yoke absent
on login and SSH shells. It preserves live SSH, terminal preference, and Linux
Claude's post-request credential refresh while restoring settings/history from
the golden. It does not give that live preservation to Codex/Cursor or macOS
Keychain. OS package fixture journals outside the home are separate and may
reverse mission changes; permanent desktop tools must remain baseline.

## 8. Recovery without changing the seal

| Refusal | Required recovery |
| --- | --- |
| `linux_desktop_stop_not_proved` | Repair termination of the named fixture desktop, then retry; other users are excluded |
| `linux_reset_claude_auth_failed` | Operator signs in and proves the live request; network/timeout failures have their own recovery |
| `linux_home_writers_stop_not_proved` | Stop the named test-home writer through its owner, then retry the sealed baseline |
| `linux_golden_home_clear_failed` | Read refused entry, resolve writer/ownership, retry; never seal the mixed home |
| `baseline_probe_failed` | Read classified cause/reason/recovery; fix auth or probe contract before re-saving |
| `linux_golden_operation_timeout` | Capture/restore allows20minutes; disconnect does not prove remote exit. Stop or wait for that process before retrying |

A timeout may leave unregistered archive/manifest or a partly restored home.
Inspect only the named destination/capture temporary paths after remote exit;
use a new capture destination or retry the existing sealed restore. Never use
an unsealed archive or edit its manifest to force acceptance. Expired sign-in
requires operator login, real request proof and a new clean golden. A successful
save alone is not a proved roundtrip.
