# Provisioning and saving a Linux Test Machine

Follow this ordered procedure as a dedicated non-root test user, from a bare
Ubuntu 24.04 host through a verified saved state. Infrastructure, account,
endpoint, project slug, passwords and baseline paths remain project-owned.
Every instruction in a numbered step inherits its audit row below.

Audit: **2026-10-02 UTC**, `linux-lab`, Ubuntu 24.04.5 arm64, user `yoketest`,
UID 1001. Registered `exec` reads and existing operation receipts were inspected;
this audit changed no configuration and executed no save/reset/verify roundtrip.
Code-reviewed contracts do not establish a new live saved-state verdict.

| Step | Audit against linux-lab on 2026-10-02 |
| --- | --- |
| 1 | Correct: non-root Ubuntu user, Git2.43/tmux3.4/Python3.12, Node18/npm, Docker29.1.3 and passwordless sudo; installing from bare unverified |
| 2 | Correct: registered SSH reachable, effective public-key yes/password and keyboard-interactive no; `.ssh` 0700/key file0600; firewall/IaC and desktop credential use unverified |
| 3 | Correct: all CLI paths present and bypass bool true; recorded capture01:01/reset04:21 receipts pass declared harness probes; new operator sign-in/requests unverified |
| 4 | Correct: XFCE, terminal helper selection, xrdp0.9.24/xorgxrdp, scrot1.10/xdotool installed; RDP127.0.0.1:3389/sesman[::1]:3350; unattended start/input timing proof unverified by this audit |
| 5 | Correct: separately recorded profile snapshot directory exists; browser sign-in and new seal/restore/UI proof unverified |
| 6–8 | Correct: registered home archive and probes present, existing capture/reset receipts pass; full digest integrity, new standard-probe coverage and new roundtrip unverified |

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
its temporary password copy. No public RDP ingress is needed. For automatic
fixture login and a bounded visible FreeRDP SDL viewer, add `--view`; the
product supplies the password on stdin and closes its forward with the viewer.
Read `--help` for the required workstation client.

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

The operator signs in as the test user in a terminal/tmux session:
Claude's documented login flow (`claude`, `/login`); Codex
`codex login --device-auth` when the [account/workspace permits it](https://developers.openai.com/codex/auth);
Cursor `NO_OPEN_BROWSER=1 agent login` and its printed URL
([authentication](https://cursor.com/docs/cli/reference/authentication)).
Installed Cursor may also expose `cursor-agent`. Operator URL/code entry is
personal; automation never enters or extracts credentials.

Require a real request from each harness, not status text or a credential-file
count. Once per machine, the operator accepts Claude's dangerous-mode prompt
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
the registered password on stdin. On the audited xrdp0.9.24 host, sesman is on
`[::1]:3350`; omitting `-s ::1` can report a connect error. Do not run a
password-bearing workaround. If the operation refuses sesrun/startup, repair
its named prerequisite and rerun. Human RDP login is used only by cases that
explicitly test human login.

For XTEST input on the actual leased display, use xdotool without `--window`;
delivery through the focused window needs several seconds before being judged
undelivered. The registered GUI-session route selects DISPLAY, XAUTHORITY and
D-Bus from the test user's actual XFCE session; a dummy display is not proof.
Prove the visible result and screenshot with `yoke test-machine screenshot
--project P --machine NAME --json`; read `--help`. Transcripts alone do not
prove the desktop. Reset ends only the exact unattended session Yoke started, checked by owner,
process start time and session identity. A human adopting it over RDP blocks
reset until that client disconnects; unowned human desktops remain protected.
Prove unattended start after a fresh-host reset, then prove reuse with a second
capture of the same display. Human logout precedes destructive baseline work.

## 5. Optional browser authorization and separate saved profile

A clean-home golden excludes the project's Yoke browser profile. Save that
profile as a separate component; it never makes a partial home a valid golden.

1. Agents use the registered test user and leased product operations to install
   the candidate and prepare its Chromium runtime and real headed desktop.
   This gives the user space for whatever sign-ins their project needs.
2. Agents open `yoke browser authorize --project P --url APPLICATION_URL`
   as the test user in the real headed desktop; read `--help`. The user chooses
   whatever sign-ins their project needs and supplies personal credentials.
   Agents complete routine setup and password-free application steps from an
   existing saved identity-provider session. Password, MFA, passkey and personal
   permission prompts require the user; agents never enter those credentials or
   change security settings.
3. The operator closes every authorization Chromium window and waits for the
   command to finish. Authorization stops the daemon before opening its plain
   Chromium and shuts that process down after its windows close. Do not start
   another browser case between this closure and capture. From the execution
   workstation, seal a new separate component:

   ```text
   yoke test-machine golden-capture --project P --machine NAME --component browser-profile --json
   ```

   Read `--help` for a new sibling destination. No probes file is needed.
   The capture refuses active writers, unavailable inventory, unsafe/foreign
   entries and occupied destinations. Private contents stay on the host;
   receipt success records `browser_profile_baseline_path` while preserving
   the clean `golden_baseline_path`. Keep the live profile if capture refuses;
   fix the named condition before resetting. Missing ancestors are created
   owner-only; existing permissions are never silently changed.
   A test-user-owned readable golden parent is permitted; other-user write
   access is refused with its path. The sealed snapshot stays owner-only.
4. Disconnect the human desktop before any destructive baseline reset. Reset
   restores the clean home and removes its live Yoke profile. Install the
   candidate, then explicitly restore before daemon startup:

   ```text
   yoke qa browser setup --project P --profile-baseline RECORDED_ABSOLUTE_PATH --json
   ```

   Exploratory walkers run this through their retained mission host-command.
   Scripted cases place this fixture after candidate installation:

   ```json
   {"id":"machine.browser-profile-restore","parameters":{"project":"CANONICAL_SLUG","baseline_path":"RECORDED_ABSOLUTE_PATH"}}
   ```

   Both routes check identity/digest and refuse an existing profile or active
   writers. Default setup and dry-run never restore a profile.
5. Start the installed candidate browser from the restored profile. Verify
   that its runtime opens on the real display and retains the separate profile.
   Archive integrity and browser liveness are separate evidence; saved sessions
   can expire even when the archive remains intact.
6. Agents perform application steps that do not need the user. Credential entry
   is a precise `HUMAN_GATE` naming the machine, current screen, needed personal
   action and resume state. Preserve the profile at a handoff. Runtime and
   inventory failures retain their named diagnostics.

Linux capture inventories writers read-only through noninteractive sudo;
archive work remains test-user-owned. The real headed session comes from the
registered XFCE desktop route in step4, never a dummy display.

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
Live `.ssh` is preserved on restore. No archive or auth material enters QA
artifacts, settings or source control.

## 7. Prove the save/reset roundtrip

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
| `linux_reset_desktop_logged_in` | Human logs out; never terminate another user's session |
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
