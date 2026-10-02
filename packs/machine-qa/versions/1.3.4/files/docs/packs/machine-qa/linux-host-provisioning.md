# Provisioning a persistent Linux Test Machine

Browser authorization uses a [separate sealed profile](browser-profile-baseline.md), captured after desktop logout and before any reset; the home golden remains free of Yoke.

Use Ubuntu 24.04 with a dedicated non-root test user and key-only SSH. Declare
`os=linux`, host, user and resource_name in its capability. Provision cloud
resources through the project's IaC surface; host settings remain project-owned.

## System tools and test user

An administrator installs the system dependencies and creates the account:

```text
sudo apt-get update
sudo apt-get install -y ca-certificates curl git tmux python3 nodejs npm docker.io
sudo systemctl enable --now docker
sudo adduser --disabled-password --gecos '' yoketest
sudo usermod -aG docker yoketest
sudo install -d -m 0700 -o yoketest -g yoketest /var/lib/yoke-golden/yoketest
```

Install the project's shared test-machine public key in this user's `.ssh`
`authorized_keys` (directory 0700, file 0600). Disable SSH password and
keyboard-interactive authentication. Restrict network access to the project's
execution machines. Log in again after group changes.

The dedicated Linux test user needs passwordless sudo, like a typical cloud VM
user. Yoke installs Chromium system libraries automatically during onboarding;
a human never enters a sudo password. Docker-group access alone is insufficient.
As the administrator, create this single drop-in (replace `yoketest` with the
actual WSL user when provisioning Ubuntu inside Windows):

```text
printf '%s\n' 'yoketest ALL=(ALL) NOPASSWD: ALL' > /tmp/yoke-test-user.sudoers
sudo -n visudo -c -f /tmp/yoke-test-user.sudoers
sudo -n install -o root -g root -m 0440 /tmp/yoke-test-user.sudoers /etc/sudoers.d/yoke-test-user
sudo -n visudo -c
sudo -n -u yoketest sudo -n true
```

Confirm the final command succeeds as the test user before onboarding; a sudo
password prompt is a provisioning failure. Repair the drop-in as administrator
and rerun validation. Keep this host setting in the project's provisioning
record. It lives outside the captured home, so home-golden restore preserves it
and this change alone needs no re-seal. If signed-in home state or declared
probes change, capture a new golden through the existing procedure.

Observe `id -u` is nonzero, `/etc/os-release` says Ubuntu 24.04, and
`git --version`, `tmux -V`, `python3 --version`, `docker info`, `sudo -n true` all succeed as
the test user. Store the shared SSH private key through the capability secret
command in [the provisioning index](host-provisioning.md), never in settings.

## Harness CLIs and headless sign-in

Run vendor installers as the test user, with `$HOME/.local/bin` on PATH:

```text
curl -fsSL https://claude.ai/install.sh -o /tmp/claude-install
bash /tmp/claude-install
npm install --global --prefix "$HOME/.local" @openai/codex
curl -fsSL https://cursor.com/install -o /tmp/cursor-install
bash /tmp/cursor-install
```

Confirm each CLI resolves in both SSH and login shells. Use each vendor's
current documented installer/runtime requirements if the host distribution's
Node version is refused. See [Claude setup](https://code.claude.com/docs/en/setup),
[Codex CLI](https://developers.openai.com/codex/cli), and
[Cursor installation](https://cursor.com/docs/cli/installation).

The operator signs in through a terminal/tmux session as the test user:

- Claude Code: start `claude`, enter `/login`, open its printed URL on a machine
  with a browser, then paste the returned code into the waiting terminal.
- Codex: run `codex login --device-auth`, open its URL and enter the printed
  one-time code. Personal security settings or a workspace administrator must
  allow device-code login. [Codex authentication](https://developers.openai.com/codex/auth).
- Cursor: run `NO_OPEN_BROWSER=1 agent login` (some installed CLIs expose the
  same executable as `cursor-agent`), then open the printed URL. Automation
  can instead receive `CURSOR_API_KEY` through the host's private credential
  mechanism. Keep the key out of argv, shell history and evidence.
  [Cursor authentication](https://cursor.com/docs/cli/reference/authentication).

Check authentication with `claude auth status`, `codex login status` and
`agent status` using the installed CLI's documented commands. Observe status,
never copy account identities or credential content into a QA receipt.
Each harness must also answer a real request; status text alone is insufficient.
Have the operator accept Claude's one-time dangerous-mode bypass prompt on the
isolated account. The standard check reads `skipDangerousModePermissionPrompt`
without writing the setting or accepting a prompt.

## Desktop for screenshots and operator browser authorization

For a persistent host that needs browser sign-in, provision a lightweight XFCE
session and xrdp using the installed Pack helper as the dedicated test user:

```text
python3 ops/machine-qa/provision_linux_desktop.py
python3 ops/machine-qa/provision_linux_desktop.py --verify
```

The helper requires Ubuntu 24.04 and passwordless sudo. It installs XFCE,
xfce4-terminal, xorgxrdp, xrdp, dbus-x11 and Python venv support, preserves another `.xsession`
selection by refusing, and proves both services plus a loopback-only RDP
listener. It selects `TerminalEmulator=xfce4-terminal` in XFCE helpers.rc while
preserving other helper settings, then proves that selection and the package.
The selection is deliberately part of the signed-in home golden. An existing desktop customization needs an operator decision before
provisioning. No cloud firewall or security-group change is needed. Installed
OS packages and services are outside the home golden; the XFCE session selection
is inside it. Provisioning is independent of the Linux QA transcript bridge.

The desktop uses normal local-account authentication. If verification reports
`login_password_set=false`, the operator sets a password interactively through
SSH with `sudo passwd <test-user>`. Keep SSH key-only. Do not disable PAM
checks or put the password in a script, a message or evidence.

For unattended desktop QA, start the test user's real XFCE/Xorg session without
an RDP client using the installed xrdp session launcher:

```text
xrdp-sesrun -s ::1 -t Xorg -F 0 <test-user>
```

This is verified on Ubuntu with xrdp 0.9.24 and sesman listening on `[::1]:3350`.
Omitting `-s ::1` uses IPv4 and failed there with
`connect error - Operation now in progress`. Supply the registered desktop
password on stdin through the capability-owned credential route; never put it
in argv, log it or write it remotely. No root session is needed. Reuse an
existing desktop rather than starting a second one. Confirm one XFCE session,
Xorg and xfdesktop are active and that a registered screenshot succeeds.
Automatic session startup by registered operations is separate work; this
recipe does not claim they already start one. A human RDP login is needed for
cases specifically testing a person's login, or as fallback when sesrun is
missing or refuses. Personal browser authorization still requires the operator.

On the operator's Mac, keep this tunnel running (substitute the registered host
and user; this is an example, not Pack configuration):

```text
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:3389:127.0.0.1:3389 <test-user>@<host>
```

In Microsoft's Windows App, add a PC named `127.0.0.1:3389`, choose no gateway
and ask for the account when connecting. Connect with the test user's local
password and select the Xorg session if prompted. The operator opens an XFCE
terminal and runs `yoke browser authorize --project P --url <application-url>`,
signs in personally, then closes every authorization window to finish. Read
`yoke browser authorize --help` for the persistent-profile contract. Never run
an automated sign-in or copy profile cookies into QA artifacts.

A desktop alone does not make a golden ready: prove each harness sign-in and
browser session, stop the browser normally, then use the registered capture
procedure. The existing fresh-host golden refuses all Yoke home residue;
authorization stores its profile in the machine-local Yoke secrets directory.
Resolve that profile-preservation baseline contract before capture rather than
baking an installed Yoke into a fresh-host snapshot.

See [xrdp listener configuration](https://github.com/neutrinolabs/xrdp/blob/devel/xrdp/xrdp.ini.in)
and [Windows App remote-PC setup](https://learn.microsoft.com/en-us/windows-app/get-started-connect-devices-desktops-apps?pivots=remote-pc).

## Yoke and the first golden

Install Yoke once using the project's distribution installer and prove
`yoke --version` and shell PATH setup. Then prepare the first **fresh** home:
Yoke/uv state, launchers and its server bundle must be absent before capture.
Keep the harness CLIs and their signed-in home state. A golden containing Yoke
would restore the very residue the fresh-host gate must prove absent.

The home archive and its digest/identity manifest are private and live outside
the home, for example beneath `/var/lib/yoke-golden/yoketest`. Capture into a
new directory; never overwrite a golden. `.ssh` is preserved from the live home,
so rotating SSH access does not get undone by restore. Live Unix sockets and
links resolving to sockets or outside the captured home are omitted regardless
of filename. Regular files and safe links named `.sock` are retained; signed-in regular
files and persistent CLI links are retained.

Omit `--probes-file` to seal the standard real-request, bypass-acceptance and
desktop-input checks. For extra checks, add entries to the captured `.probes`
sidecar while retaining every standard name: for example `/usr/bin/docker info`
or `/usr/bin/systemctl --user is-active UNIT`. Capture runs canonical standard
programs plus the extra checks over SSH; credential files alone do not prove
a live login. Remove Yoke installation/session residue before capture, retaining
signed-in harnesses and remote-access credentials.

```text
yoke test-machine golden-capture --project P --machine NAME --destination /var/lib/yoke-golden/yoketest/home
yoke test-machine reset --project P --machine NAME --baseline fresh-host
yoke test-machine verify --project P --machine NAME
yoke test-machine bridge-diagnose --project P --machine NAME
```

Verify restores the golden and exercises both baselines, ending with Yoke
installed. Reset reaches only the requested baseline. Archive identity, digest,
unsafe entries, residue, probe failures and transport failures all refuse by
name with a recovery step. Repair the named condition before retrying.

## Evidence and expired logins

The Linux bridge uses tmux for input/transcripts and XFCE for visible terminal
checkpoints. Run `yoke test-machine screenshot --project P --machine NAME --json`
to capture the actual desktop as a validated PNG artifact. The capture discovers
exactly one XFCE session owned by the SSH user and uses that session's DISPLAY,
XAUTHORITY and D-Bus address. A missing or ambiguous session requires provisioning
and one unlocked desktop session, started with sesrun or the RDP fallback above;
no dummy display or transcript earns screenshot credit.
The provisioner installs `scrot` and `xdotool` alongside XFCE. Provision these
before capturing a new golden so they belong to the package baseline. QA
package restoration purges additions to its journal's baseline inventory;
installing `xdotool` during a mission does not establish a durable prerequisite.
Prove `Linux desktop input available` after a `fresh-host` reset roundtrip.
For XTEST keys, focus the target window, omit `--window`, and allow several
seconds for delivery before deciding that input failed. A browser approval
recipe still records `headless_linux_browser_approval_unavailable`; browser sign-in
is the operator's provisioning step. Keep private windows out of capture when required.

When a restored login expires, sign in again as the same user, prove all
probes, remove Yoke residue and capture a **new** golden with the updated probes.
The capture records its new path only after success. Do not edit a sealed
archive or its manifest to make expired authentication appear ready.

Retain capture, fresh-host reset and verify receipts. A headless Linux host
needs no desktop input tool; desktop hosts must pass the sealed input check
after reset, not only before capture.

### Standard capture checks

- `Claude real request`, `Codex real request`, `Cursor real request`: each CLI answers.
- `Claude bypass accepted`: the operator accepted its one-time warning.
- `Linux desktop input available`: desktop hosts have xdotool after restore;
  headless hosts pass without it.

A supplied probe document must include every name above; missing names refuse
as `baseline_standard_probes_missing`. Start from the current `.probes` sidecar
for extra checks. Capture always runs/seals canonical standard programs plus
the extras; it never carries an older sidecar forward implicitly. A failed
standard check names the provisioning repair and cannot register a new golden.
Harness output stays on the host; retain only readiness results in evidence.
