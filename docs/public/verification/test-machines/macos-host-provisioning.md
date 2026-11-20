# Provisioning and saving a macOS Test Machine

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > macOS host provisioning
<!-- /yoke:breadcrumbs -->

Follow the [normal-user installation rule](index.md#install-as-the-test-user).

For stored-password setup commands on macOS and Linux, follow [administrator commands](administrator-commands.md).

Follow [setup responsibilities](setup-responsibilities.md) and the project-owned
manual preparation inventory in the [provisioning index](host-provisioning.md).

Follow this procedure as the dedicated test account, from a bare host through
a proved saved state. Substitute the project's registered host, user, machine
name and project slug; these values and credentials are project-owned.

## 1. Dedicated account and identity

Use a Mac with at least 40 GiB on its system volume
([disk sizing](host-provisioning.md#disk-sizing-and-online-resize)). Create one
dedicated Administrator account in Users & Groups and choose its short name
before registration. Stored-password setup needs administrator access. Set a
deliberate computer name. Keep every other account outside the fixture.
Check `id -un`, `scutil --get ComputerName`, `scutil --get LocalHostName`, and
`stat -f %Su /dev/console`; the graphical console must belong to the test user.

### Join Tailscale before registration

Follow [tailnet bootstrap](tailnet-bootstrap.md) for provider start, current-IP
SSH, stable lab naming and operator sign-in approval before these OS checks.

Install Tailscale on the host and join the operator's tailnet by completing its
sign-in flow. Enable startup/unattended operation and disable device key expiry
in the admin console. Controllers join the same tailnet and use MagicDNS.
This is one-time manual machine setup.

On supported macOS versions, install the [standalone macOS client](https://tailscale.com/download/mac),
open it and approve its VPN/system extension. Complete sign-in, enable launch
at startup and prove reachability after logout/reboot. Existing test Macs join
or retain this same tailnet; their system Tailscale state stays outside goldens.
Use the client CLI at `/Applications/Tailscale.app/Contents/MacOS/Tailscale`
for the status command below. For macOS 12, use the
[documented exception](#macos-12-only).

Complete the [Remote Login setup](#3-remote-login-and-full-disk-access) before
proving SSH. Read `Self.DNSName` from `tailscale status --json`, trim the trailing dot and
resolve that exact MagicDNS name from the controller. Prove OpenSSH key login,
then register it as `host`. For a physical Mac, read the ED25519 fingerprint at
the console with `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`. Compare it
with the fingerprint of the key from `ssh-keyscan -t ed25519 HOST`. Add that
entry under the exact MagicDNS hostname to
`~/.yoke/test-machine/known_hosts` after the fingerprints match. Prove the
machine key works using the Yoke file and strict host-key checking. If SSH
refuses it, check the Remote Login allowlist and the test account’s authorized
keys and ownership in [step 3](#3-remote-login-and-full-disk-access).
For cloud bootstrap, query the provider's **current** public IP and connect with
the [bootstrap SSH command](tailnet-bootstrap.md#start-the-lab-and-reach-its-current-address);
never register that IP.
Use key-only public SSH for cloud bootstrap and keep desktops on private routes.
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

## 2. Network, capability and desktop route

Provision infrastructure through the project's IaC or an explicit operator
exception. Register the verified MagicDNS name and follow the
[network access requirements](host-provisioning.md#network-access).
Declare `desktop_route=direct` as the default route for a physical Mac reachable over the
tailnet. Keep VNC off the public internet. In Screen Sharing settings, allow
the dedicated `desktop_user` to connect and control the desktop. Use its account
password for authenticated Screen Sharing. If the viewer requires a VNC-only
password, enable **VNC viewers may control screen with password** and set a
separate VNC-only password. [Apple Screen Sharing settings](https://support.apple.com/guide/mac-help/mh11848/mac)

Register the Test Machine by name using `yoke test-machine settings-replace --test-machine NAME --settings-file FILE --new`; read `--help` before
an update, which uses the as-read settings token. Declare `resource_name`,
`os=macos`, `host`, `user`, and an eventual absolute `golden_baseline_path`
outside that user's home. Desktop settings are `desktop_route=direct`,
`desktop_protocol=vnc`, `desktop_port=5900`, and `desktop_user`, with no
`desktop_host` so Screen Sharing reaches the MagicDNS host over the tailnet. A
host outside the tailnet uses `desktop_route=ssh-forward`. Set
`operating_notes` to record the model, architecture, OS version, console and
routing constraints. Keep credentials out of these notes. Register relay
capacity under a separate identity with its own home.
Set and maintain [capability tags](host-provisioning.md#register-capability-tags) before verifying.

On every QA execution workstation, import the Test Machine's SSH private key:

```text
yoke test-machine secret set --test-machine NAME --key ssh_private_key --value-file KEY_FILE
yoke test-machine secret set --test-machine NAME --key desktop_password --value-file PASSWORD_FILE
yoke test-machine get --test-machine NAME
yoke test-machine exec --test-machine NAME -- /usr/bin/true
```

Stage the desktop password in an owner-only file and remove that copy after
a successful import. Read each command’s `--help`. Keep secret values out
of settings, prompts, command arguments and logs.
`exec` uses the workstation's SSH agent; an unavailable agent is not proof that
the capability-owned private key is missing. A serial host lease held by
another session must be released before preparation or ad hoc access.

For operator desktop access, use `yoke test-machine desktop-access
--test-machine NAME`. Read `--help`, open its returned address in Screen Sharing,
and use the password from its private mode-0600 `password_file`, never output
the file. On the SSH-forward fallback the address works while the command runs;
press Enter there to close the forward. Remove only that command's temporary
password copy after closing access.

## 3. Remote Login and Full Disk Access

Enable Remote Login for the dedicated user and install the machine's public key
as its own line in `~/.ssh/authorized_keys`. Set the directory to mode 0700
and the file to mode 0600, both owned by the dedicated account. Confirm the
account is on the Remote Login allowlist before attempting SSH.
On current macOS use System Settings → General → Sharing; Monterey uses
System Preferences → Sharing. Menu placement differs by release.
Allow full disk access for remote users. The capture/restore process needs
effective Full Disk Access, not just working SSH. The responsible Remote Login
process is `/usr/libexec/sshd-keygen-wrapper`.

Establish consent in the OS settings UI under [setup responsibilities](setup-responsibilities.md). Do not query or
edit the system privacy database. Capture/restore's own Full Disk Access gate
and complete-copy evidence prove its access; SSH reachability alone does not.
Grant Terminal Full Disk Access separately only if it actually performs a
whole-home operation. A revoked system grant survives a home restore as revoked.

## 4. Unattended login and power

For an operator-approved unattended test rig, turn FileVault off, enable
automatic login for the dedicated user in Users & Groups, and set the password
delay in Lock Screen to Never. Use these settings only on a dedicated fixture.
Require `fdesetup status` to report FileVault off. Verify `defaults read
/Library/Preferences/com.apple.loginwindow autoLoginUser` and
`stat -f %Su /dev/console` both name the dedicated user.
In General → Software Update → Automatic Updates, disable automatic macOS
downloads and installation for a fixture whose OS is managed manually.
Disable system, display and disk sleep permanently.

```text
sudo pmset -a sleep 0 displaysleep 0 disksleep 0
pmset -g
```

All three must read 0. Screen Sharing can temporarily prevent sleep and hide
a bad permanent setting. Disconnect it and check the unattended state.
Do not silently change a discrepant security or power setting during an audit.

## 5. Screen saver and login keychain before saving

As the test console user, set the screen saver to Never **before capture**:

```text
defaults -currentHost write com.apple.screensaver idleTime -int 0
defaults -currentHost read com.apple.screensaver idleTime
```

Require 0 again after reset. An unset value is the 20-minute default in Yoke's
macOS check, not Never. The ByHost preference is home state: restoring an older
golden can erase the setting. A live fix without a new golden does not persist.

Whenever the test login password changes, re-key the login keychain with
`security set-keychain-password` in the GUI Terminal **before** signing in
again. Product code supplies old/new passwords from stored secrets under
[setup responsibilities](setup-responsibilities.md); never put them in
arguments or evidence. The keychain stays live through resets rather than being
captured, so the re-keyed keychain persists without a new golden; an
un-re-keyed one rejects the new login password (`-25293`).

In the GUI Terminal, check `security show-keychain-info
~/Library/Keychains/login.keychain-db`: it must be unlocked with no timeout
(use `security set-keychain-settings` there when adjustment is needed).
Automatic login supplies the graphical session; it does not give an SSH login
keychain access. SSH `-25308`/“User interaction is not allowed” is a session
boundary, not proof of expired sign-in. Never export Keychain credentials to
make an SSH command work. Disconnect Screen Sharing after GUI preparation;
its curtain can lock the physical display while the remote viewer looks unlocked.

## 6. Tools and harnesses

Install Command Line Tools once with `xcode-select --install`, finish the
dialog locally, then prove `git --version` returns immediately. Full Xcode is
not required. A bare Mac's Git shim can raise a dialog nobody sees over SSH.
Keep the existing GNU `screen`. The macOS bridge uses Terminal.app.

Install [Homebrew](https://docs.brew.sh/Installation) as the dedicated account.
On Apple silicon, use a native arm64 Terminal and the `/opt/homebrew` prefix.
On Intel, use `/usr/local`. Follow the installer's `brew shellenv` instructions
and prove `brew --version` in a new login Terminal. For unattended Apple
silicon setup, download the signed `Homebrew.pkg` from the official release,
check it with `pkgutil --check-signature`, then use the registered administrator
command to run `installer -pkg PACKAGE -target /` while the test user is the
active console user. Run later `brew` commands as the test account.

Install the required harness apps and vendor CLIs as the test user. Use the
current [Claude installer](https://code.claude.com/docs/en/setup),
[Codex CLI installer](https://developers.openai.com/codex/cli), and
[Cursor installer](https://cursor.com/docs/cli/installation). Reopen a login
Terminal and check that each prints its version. A non-login SSH PATH may omit `.local/bin`;
that is not an absent CLI. Declare actual executable paths for probes. Open each
desktop app from the test account once and complete its first-run prompts in the
GUI. Download [Claude](https://claude.com/download),
[ChatGPT with Codex](https://chatgpt.com/download) and
[Cursor](https://cursor.com/download) in the test user's browser. Drag each app
to Applications. Leave credential prompts open for the operator.
Check each vendor's current supported OS list before choosing coverage. An
existing executable does not prove that the host supports a new installation.
Golden refresh proves each CLI with `--version` in the GUI session. If a new
release fails, refresh reports the exit code and keeps a runnable prior one.
Cursor keeps releases in `~/.local/share/cursor-agent/versions/`. Refresh
re-points both CLI links and runs `set-channel static` on the retained CLI to
prevent a request from relinking the broken release. Later plans retry the
vendor installer. If no version runs, install a supported release as the test
user, prove `--version` in Terminal, and retry.

For self-host cases, download [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/)
and drag Docker to Applications. Open it as the test user and have the
operator accept the Docker Subscription Service Agreement. Keep the default
user-scoped setup. Verify `~/.docker/bin/docker version` and
`~/.docker/bin/docker compose version`. The reset removes the labeled self-host
stack and keeps Docker Desktop's VM data live outside the golden. If the reset
starts Docker Desktop, it quits it again after verification.

### macOS 12 only

On macOS 12, use [Colima](https://colima.run/docs/installation/) for Docker
and Compose. Choose versions that support the installed OS. Initialize the
runtime and verify `docker run --rm hello-world` and `docker compose version`
before stopping it. Set `COLIMA_HOME`, `LIMA_HOME` and `COLIMA_CACHE_HOME`
in `~/.zshenv` to owner-only directories outside the captured home and
golden retention directories. Use the Homebrew Tailscale formula on macOS 12 and verify the existing
service and tailnet connection after reboot. The current standalone app
requires a newer version of macOS.

## 7. Effective privacy and terminal control

In Privacy & Security (Security & Privacy on Monterey), grant every pair.
The Remote Login controller is `/usr/libexec/sshd-keygen-wrapper`.

| Grant | Client | Target |
|---|---|---|
| Automation | Remote Login controller | System Events, Terminal |
| Automation | Terminal.app | System Events |
| Device Control and Data Access (Accessibility on older macOS) | Remote Login controller | — |
| Device Control and Data Access (Accessibility on older macOS) | Terminal.app | — |
| Screen & System Audio Recording (Screen Recording on older macOS) | Terminal.app and, when macOS attributes remote capture to it, the Remote Login controller | — |

SSH `osascript` Terminal control uses the Remote Login controller.
The helper shows separate macOS consent prompts for System Events and
Terminal as the bridge reaches each step. Allow each on the fixture console,
then retry the bridge to verify it. In macOS 27, **Device Control and Data
Access** replaces the **Accessibility** row in Privacy & Security. If the
helper is absent from that list, use **+**, press Command+Shift+G, and enter
`/usr/libexec/sshd-keygen-wrapper`. Enable the helper's toggle. A grant for
Terminal alone still leaves the remote keystroke check refused.
On macOS 27, TCC can attribute `screencapture` from an SSH-driven Terminal
command to the Remote Login controller. Keep Terminal enabled for local
capture. On the dedicated test Mac, add `/usr/libexec/sshd-keygen-wrapper`
under **Screen & System Audio Recording** if TCC names it for the failed
capture. Then rerun `bridge-diagnose` and verify that it captures window content.
Before sealing a fresh golden, separately enable **Terminal.app** under
**Device Control and Data Access** on the unlocked test desktop. Add it with
**+** if absent, approve its prompt, and verify GUI input and readback.

GUI-session commands (`--gui-session`) also need Terminal → System Events. Safari
needs no grant: browser approval runs in the operator identity's Chromium
through the installed Yoke, not AppleScript. A checked Automation box alone does not prove consent: macOS can
still hold an unanswered prompt. At the host console, open Terminal and run:

```sh
osascript -e 'tell application "System Events" to count processes'
```

Click **OK** on the “Terminal wants access to control System Events” prompt.
On older macOS, also tick Terminal's System Events row in System Preferences
if it opens. Confirm with the `bridge-diagnose` command below before capture
or QA. Follow
[setup responsibilities](setup-responsibilities.md) for OS privacy/TCC consent.

Disable Terminal → Secure Keyboard Entry. Prove control through the registered
operation that needs it, not a permission-row inventory:

```text
yoke test-machine bridge-diagnose --test-machine NAME
yoke test-machine screenshot --test-machine NAME --json
```

Read `--help`. These operations take the host lease. If the bridge reports
`terminal_display_locked`, unlock the dedicated account at the physical
console, confirm that Terminal is open, and rerun without Screen Sharing.
Diagnosis creates and drives a temporary
Terminal window and checks transport, console/lock, AppleEvents, secure entry,
display geometry, launch/focus, input, transcript and real capture in order.
Unreached checks are not run. Screen Recording proof requires window content,
not wallpaper; two captures around an authorized window change should differ.
Before probing GUI-session commands, read the mandatory
[macOS automation diagnostics](browser-identities.md#macos-automation-diagnostics)
for denial, timeout and Terminal-window recovery.

Continue with [harness sign-in and baseline recovery](macos-baseline-recovery.md#8-harness-sign-in-and-acceptance-set)
to sign in, seal and prove the setup, and add QA plans.
