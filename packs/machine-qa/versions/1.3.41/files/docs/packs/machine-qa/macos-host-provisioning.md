# Provisioning and saving a macOS Test Machine

For stored-password setup commands on macOS and Linux, follow [administrator commands](administrator-commands.md).

Follow [setup responsibilities](setup-responsibilities.md) for every step.

Follow this procedure as the dedicated test account, from a bare host through
a proved saved state. Substitute the project's registered host, user, machine
name and project slug; these values and credentials are project-owned.

## 1. Dedicated account and identity

Use a Mac with at least 40 GiB on its system volume
([disk sizing](host-provisioning.md#disk-sizing-and-online-resize)). Create one
dedicated test user and choose its short name before registering the
capability. Set a deliberate computer name. Never rename the test user or
enumerate, capture, restore, or log out another operator account.
Check `id -un`, `scutil --get ComputerName`, `scutil --get LocalHostName`, and
`stat -f %Su /dev/console`; the graphical console must belong to the test user.

## 2. Network, capability and desktop route

Provision infrastructure through the project's IaC or an explicit operator
exception. Join the private network and register a stable DNS name, not a
transient address. A rebuild may require the operator to retire the old network
node before enrollment so the name is not changed to a suffixed variant.
Restrict remote access to the execution machines; do not expose SSH or VNC by
router forwarding. Enable Screen Sharing for the dedicated account when needed.

Register `test-machine:<name>` using `yoke test-machine settings-replace
--project P --machine NAME --settings-file FILE --new`; read `--help` before
an update, which uses the as-read settings token. Declare `resource_name`,
`os=macos`, `host`, `user`, and an eventual absolute `golden_baseline_path`
outside that user's home. Desktop settings are `desktop_route`,
`desktop_protocol=vnc`, `desktop_port`, and `desktop_user`; optional
`desktop_host` names a separate endpoint. A relay capacity registration is a
separate identity; ordinary work must use a different home from test resets.

On every QA execution workstation, store the project's shared SSH private key:

```text
yoke projects capability secret set --project P --cap-type test-machine --key ssh_private_key --value-file KEY_FILE
yoke projects capability secret set --project P --cap-type test-machine:NAME --key desktop_password --value-file PASSWORD_FILE
yoke test-machine get --project P --machine NAME
yoke test-machine exec --project P --machine NAME -- /usr/bin/true
```

Read each command's `--help`. The shared public key authorizes all project test
hosts. Secret values never enter settings, prompts, command arguments or logs.
`exec` uses the workstation's SSH agent; an unavailable agent is not proof that
the capability-owned private key is missing. A serial host lease held by
another session must be released before preparation or ad hoc access.

For operator desktop access, use `yoke test-machine desktop-access --project P
--machine NAME`. Read `--help`, open its returned address in Screen Sharing,
and use the password from its private mode-0600 `password_file`, never output
the file. If the route uses SSH forwarding, close the returned control socket
after use: `ssh -F /dev/null -S PASSWORD_FILE.ssh -O exit SSH_USER@SSH_HOST`.
Remove only that command's temporary password copy after closing access.

## 3. Remote Login and Full Disk Access

Enable Remote Login for the dedicated user and install the shared public key
in `~/.ssh/authorized_keys` (directory 0700, file 0600, test-user-owned).
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
automatic login for the dedicated user, and turn screen lock off. These are
security choices for a dedicated fixture, not defaults for personal Macs.
Observe `fdesetup status` and `defaults read
/Library/Preferences/com.apple.loginwindow autoLoginUser`.
Disable system, display and disk sleep permanently:

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
Keep the existing GNU `screen`; the macOS bridge uses Terminal.app.

Install the required harness apps and vendor CLIs as the test user. Use the
current [Claude installer](https://code.claude.com/docs/en/setup),
[Codex CLI installer](https://developers.openai.com/codex/cli), and
[Cursor installer](https://cursor.com/docs/cli/installation). Reopen a login
Terminal and check that each prints its version. A non-login SSH PATH may omit `.local/bin`;
that is not an absent CLI. Declare actual executable paths for probes.
Check each vendor's current supported OS list before choosing coverage. An
existing executable does not prove that the host supports a new installation.
Golden refresh proves each installed CLI with `--version` in the GUI session.
If a new binary cannot run, it restores a runnable prior version and reports
`held back: HARNESS VERSION does not run on this host` with its exit code and
stderr. Cursor releases remain under `~/.local/share/cursor-agent/versions/`;
refresh selects the newest runnable one and re-points both CLI links. Keep
those releases. A held-back CLI is accepted for this host and captured in its
new golden. With no runnable version, refresh stops naming the harness and
error; install a supported version as the test user, prove `--version` in
Terminal, then rerun the plan. Installer success alone proves nothing.

## 7. Effective privacy and terminal control

In Privacy & Security (Security & Privacy on Monterey), grant every pair.
The Remote Login controller is `/usr/libexec/sshd-keygen-wrapper`.

| Grant | Client | Target |
|---|---|---|
| Automation | Remote Login controller | System Events, Terminal, Safari |
| Automation | Terminal.app | System Events, Safari |
| Accessibility | Remote Login controller and Terminal.app | — |
| Screen Recording | Terminal.app | — |

SSH `osascript` browser approval uses the Remote Login controller. GUI-session
commands (Safari approval helper and `--gui-session`) need Terminal → System
Events. Older macOS opens System Preferences instead of a consent dialog:
tick Terminal's Automation row by hand. Follow
[setup responsibilities](setup-responsibilities.md) for OS privacy/TCC consent.

Disable Terminal → Secure Keyboard Entry. Prove control through the registered
operation that needs it, not a permission-row inventory:

```text
yoke test-machine bridge-diagnose --project P --machine NAME
yoke test-machine screenshot --project P --machine NAME --json
```

Read `--help`; these take the host lease. Diagnosis creates/drives a temporary
Terminal window and checks transport, console/lock, AppleEvents, secure entry,
display geometry, launch/focus, input, transcript and real capture in order.
Unreached checks are not run. Screen Recording proof requires window content,
not wallpaper; two captures around an authorized window change should differ.
Before probing GUI-session commands, read the mandatory
[macOS automation diagnostics](browser-identities.md#macos-automation-diagnostics)
for denial, timeout and Terminal-window recovery.

## 8. Harness sign-in and acceptance set

Agents start each required harness's vendor login flow from the test user's
**GUI Terminal** and approve its device code in the signed-in browser; the
operator types only their password where the vendor asks. Follow the [browser identity procedure](#11-live-browser-identities)
for password-free native authorization and personal sign-in handoffs. [Codex device auth](https://developers.openai.com/codex/auth)
requires account/workspace permission. [Cursor auth](https://cursor.com/docs/cli/reference/authentication)
is separate from app presence. A login-status line or credential file is
insufficient: every harness must answer a real request without tool calls.
Save every completed sign-in, including a Safari sign-in, at once with
`yoke test-machine golden-capture` (section 9): it quits Safari, proves the
real requests and recaptures the baseline.

Once per machine, accept Claude's dangerous-mode prompt in the
dedicated test context. Require `skipDangerousModePermissionPrompt=true` in
its vendor settings before saving; a restore brings back the captured value.
This deliberate fixture choice does not authorize unrelated bypasses.

Before capture, prove steps 1–7, keychain readability in the GUI context,
screen saver 0, and real requests from Claude, Codex and Cursor. Golden capture
uses the standard macOS probes when no file is supplied. A custom `--probes-file`
must include every standard check and may add requirements. The standard set
includes native real requests, bypass acceptance, GUI keychain readability,
and screen-saver Never. The exact names are `Claude real request`,
`Codex real request`, `Cursor real request`, `Claude bypass accepted`,
`macOS login keychain readable`, and `macOS screen saver disabled`.
Missing names refuse as `baseline_standard_probes_missing`. Capture always
runs/seals the canonical standard programs plus extras; an older sidecar is
never carried forward implicitly. Native output and Keychain contents stay on
the host. Extra probes name absolute argv and optional
`expect_output_contains`; use macOS's guaranteed `/bin/test` for file checks.

## 9. Save a clean home

Keep signed-in vendor state but remove Yoke/uv state through the registered
baseline preparation path. Harness logins themselves are never captured: the
login Keychain (`Library/Keychains`, holding Claude's and Cursor's logins),
`.claude/.credentials.json`, `.codex/auth.json`, the browser identity store
`.yoke-browser-identities` and Safari's cookie store
(`Library/Containers/com.apple.Safari/Data/Library/Cookies`) are excluded from
the golden and kept live on every reset, so a reset never puts back a rotated
token or cookie. Safari writes its cookies when it quits, so capture and reset
first ask a running Safari to quit and wait up to 30 seconds for it to exit;
they never force-quit it. If a previous golden exists, reset first, then make
the operator preparations above and re-save. The first bare home needs no
Yoke installation before capture. Never seal a home containing Yoke residue.
Choose a new absolute destination outside the test home, preferably a sibling
of its current golden; do not overwrite a saved baseline:

```text
yoke test-machine golden-capture --project P --machine NAME --destination /Users/Shared/yoke-golden/TESTUSER-home-DATE
```

Read `--help` for default destination and custom probes. Probes run in the GUI
Terminal context. A failed capture does not replace the registered baseline.
The captured directory, `.manifest`, `.probes` and `.harness-clis` stay private on the host.
Golden capture records each CLI's version beside the golden in
`GOLDEN.harness-clis`. Before a QA plan's first reset on this host, Yoke
compares those versions with each vendor's latest release; when one is newer
it resets, installs the newer CLIs with each vendor's installer as the test user and
captures a new golden under the plan's own host lease. Do not hand-update
CLIs for QA; a failed refresh stops the plan with the step to repair.
Their seal records identity, size and probe digest; captured files retain modes
and ACLs. Sockets/FIFOs are omitted by type, regular `.sock` files are retained.
The exact OS-managed audiovisual preference at
`Library/Group Containers/group.com.apple.secure-control-center-preferences/Library/Preferences/group.com.apple.secure-control-center-preferences.av.plist`
is excluded from capture and preserved live on reset alongside `.ssh`, user
TCC and the harness logins above. When present it must be a root:wheel regular
file with no symlink ancestors. Its declaration is sealed in the manifest; every
other foreign entry refuses. Do not change its owner or ask the operator to
repair it. The manifest also seals the whole preserved list as
`preserved_home_entries`. Older manifests remain readable and their captured
copies of preserved entries are never restored; a present declaration may name
only kept entries, and every entry it declares must be absent from the golden.
An entry kept only since the golden was sealed, such as Safari's cookie store,
stays inert in it and the live copy is kept.
Only the dedicated test home is captured; system settings/other homes are not.

| Named refusal | Recovery |
| --- | --- |
| `golden_capture_yoke_residue` | Return to the existing baseline, then prepare and save again |
| `golden_capture_foreign_owner` | Diagnose the unexpected owner's writer; prove a product-owned restoration path before capture |
| `golden_capture_preserved_state_invalid` | Inspect the named OS entry's owner/type or symlink ancestor; preserve content and do not change its owner |
| `golden_capture_destination_occupied` | Choose a new destination |
| `test_machine_sign_in_app_quit_not_proved` | The named app did not quit. Quit it on the machine, answering any prompt it shows, then retry. If `quit_requested` is false, allow the SSH session to control it under Privacy & Security > Automation |
| `baseline_probe_failed` | Read cause/reason/recovery and sanitized native exit diagnostics. Nonzero execution retains its category; reason/recovery names quota, authentication, model or transport evidence. Quota waits for provider capacity; only diagnosed auth calls for sign-in. Preserve the golden and failed capture; never reset credentials to clear quota |
| `baseline_probe_bridge_unavailable` | Repair the named bridge condition, then retry |
| `test_machine_terminal_quit_not_proved` | Terminal survived its quit and a forced kill. Quit it at the console (Terminal > Quit Terminal, then Terminate), then retry |
| `test_machine_terminal_relaunch_failed` | The home was restored but Terminal opened no window. Open Terminal at the console, then run `yoke test-machine bridge-diagnose` |
| `test_machine_terminal_probe_failed` | Yoke could not read whether Terminal runs. Repair SSH to the machine, then retry |
| `golden_capture_copy_home_failed` | Read quoted `copy_stderr`; repair its reported cause, then save to a new destination. Copy tools use `LC_ALL=en_US.UTF-8` so SSH caller locales do not cause warnings |

Never discard copy errors, change a sealed manifest, or make the golden
writable to force acceptance. Live destination ACL/mode preparation is the
registered reset's responsibility; partial clear/copy is a failed operation.

## 10. Prove the saved state and restore it

These commands are **destructive**, deliberately authorized provisioning work:

```text
yoke test-machine verify --project P --machine NAME
yoke test-machine reset --project P --machine NAME --baseline fresh-host
yoke test-machine get --project P --machine NAME
```

Read their `--help`. Verify reaches both baselines and ends `shell-preconfigured`
with the current Yoke launcher installed. Reset reaches one baseline;
`fresh-host` returns the clean signed-in home, not a blank user. The operation
retains live SSH, privacy and harness-login state, stops owned services/writers,
clears product residue, restores content/modes and runs sealed probes. It quits
Terminal, killing it and its window processes if a sheet blocks the quit.
After restore it relaunches Terminal without saved windows to avoid probe stalls.
The restore merges each captured directory into place with `ditto`, so a macOS
daemon recreating its directory mid-restore does not fail it. Restoring a home
cannot restore an external grant. A login that expires on the live host is
fixed by signing in again in the GUI; the kept-live login survives the next
reset, and `yoke test-machine golden-capture` saves the rest of that signed-in
state into the baseline. Reset refuses `test_machine_sign_in_app_quit_not_proved`
before clearing when Safari will not quit. Recheck screen saver 0 and
the GUI keychain after the roundtrip, with Screen Sharing disconnected.

Require passing operation receipts bound to the new golden, standard checks,
and real desktop/input evidence. If authentication expires, agents rerun the
GUI login (the operator types only the password) and save it with
`yoke test-machine golden-capture`; the next
reset keeps that login. Never recapture a mixed home
after a failed restore. Capture then verify/reset is one ordered saved-state
proof; an old receipt or a successful capture alone cannot replace it.

## 11. Live browser identities

Required authorization behavior:

Run yoke browser authorize to check automation identities and Test Machine
desktop browser sign-ins. It opens tabs only for expired sites and names the
account to use. Desktop browser sign-ins stay live through reset and are
excluded from golden snapshots.

The remote `--machine NAME` command includes both checks by default; there
is no desktop opt-out. Confirm release-matched help and operation receipts
before relying on an installed release. Before running it, read the complete
[desktop browser checks](browser-identities.md#desktop-browser-checks) procedure.

1. Apply the project-owned sign-in policy. The human only types their own
   password or credential; agents complete every other prompt.

Before sign-in, follow the complete [macOS sign-in
procedure](browser-identities.md#macos-sign-in-procedure).
