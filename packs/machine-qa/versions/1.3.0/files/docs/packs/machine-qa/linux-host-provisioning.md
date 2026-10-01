# Provisioning a persistent Linux Test Machine

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

## Optional desktop for operator browser authorization

For a persistent host that needs browser sign-in, provision a lightweight XFCE
session and xrdp using the installed Pack helper as the dedicated test user:

```text
python3 ops/machine-qa/provision_linux_desktop.py
python3 ops/machine-qa/provision_linux_desktop.py --verify
```

The helper requires Ubuntu 24.04 and passwordless sudo. It installs XFCE,
xorgxrdp, xrdp, dbus-x11 and Python venv support, preserves another `.xsession`
selection by refusing, and proves both services plus a loopback-only RDP
listener. An existing desktop customization needs an operator decision before
provisioning. No cloud firewall or security-group change is needed. Installed
OS packages and services are outside the home golden; the XFCE session selection
is inside it. Provisioning is independent of the Linux QA transcript bridge.

RDP uses normal local-account authentication. If verification reports
`login_password_set=false`, the operator sets a password interactively through
SSH with `sudo passwd <test-user>`. Keep SSH key-only. Do not disable PAM
checks or put the password in a script, a message or evidence.

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

Declare a probes JSON document with absolute argv for every required CLI,
credential file and relevant user service. Example entries (resolve the actual
binary and credential paths from the provisioned user's installation):

```json
{"probes":[
  {"name":"Claude authenticated","argv":["/home/yoketest/.local/bin/claude","auth","status"]},
  {"name":"Codex authenticated","argv":["/home/yoketest/.local/bin/codex","login","status"]},
  {"name":"Cursor authenticated","argv":["/home/yoketest/.local/bin/agent","status"]},
  {"name":"Codex credential file","argv":["/usr/bin/test","-s","/home/yoketest/.codex/auth.json"]},
  {"name":"Docker ready","argv":["/usr/bin/docker","info"]}
]}
```

For any required user unit, add `/usr/bin/systemctl --user is-active UNIT`.
Run each declared probe before sealing it; a present credential file alone
cannot prove its login is live. Probes run over SSH on Linux.

```text
yoke test-machine golden-capture --project P --machine NAME --destination /var/lib/yoke-golden/yoketest/home --probes-file probes.json
yoke test-machine verify --project P --machine NAME
yoke test-machine bridge-diagnose --project P --machine NAME
yoke test-machine reset --project P --machine NAME --baseline fresh-host
```

Verify restores the golden and exercises both baselines, ending with Yoke
installed. Reset reaches only the requested baseline. Archive identity, digest,
unsafe entries, residue, probe failures and transport failures all refuse by
name with a recovery step. Repair the named condition before retrying.

## Evidence and expired logins

The Linux bridge uses tmux, proving input and captured transcript. Screenshot
or GUI-session proof records `headless_linux_screenshot_unavailable` with a
macOS recovery. A browser approval recipe records
`headless_linux_browser_approval_unavailable`; headless sign-in is the operator's
provisioning step. A designed deferral cannot satisfy screenshot evidence.

When a restored login expires, sign in again as the same user, prove all
probes, remove Yoke residue and capture a **new** golden with the updated probes.
The capture records its new path only after success. Do not edit a sealed
archive or its manifest to make expired authentication appear ready.
