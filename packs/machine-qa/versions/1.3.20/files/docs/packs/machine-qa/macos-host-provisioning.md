# Provisioning and saving a macOS Test Machine

For stored-password setup commands on macOS and Linux, follow [administrator commands](administrator-commands.md).

Follow [setup responsibilities](setup-responsibilities.md) for every step.

Follow this procedure as the dedicated test account, from a bare host through
a proved saved state. Substitute the project's registered host, user, machine
name and project slug; these values and credentials are project-owned.

## 1. Dedicated account and identity

Create one dedicated test user and choose its short name before registering
the capability. Set a deliberate computer name. Never rename the test user or
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
Terminal and record their versions. A non-login SSH PATH may omit `.local/bin`;
that is not an absent CLI. Declare actual executable paths for probes.
Check each vendor's current supported OS list before choosing coverage. An
existing executable does not prove that the host supports a new installation.

## 7. Effective privacy and terminal control

In Privacy & Security (Security & Privacy on Monterey), grant:
Accessibility and Automation for Terminal/System Events to the Remote Login
controller `/usr/libexec/sshd-keygen-wrapper`; Screen Recording to Terminal.app
for GUI-bridge capture. Give Terminal other grants only when its own probe
needs them. Follow [setup responsibilities](setup-responsibilities.md) for OS privacy/TCC consent dialogs.

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
`-25211` names Accessibility; `-1743` names Automation. Repair the named grant
through the UI and rerun. An active Screen Sharing curtain must be disconnected
or reconnected without curtain. A home restore cannot recreate these grants.

## 8. Operator sign-in and acceptance set

Sign in each required harness from the test user's **GUI Terminal** using its
vendor login flow. Follow the [browser identity procedure](#11-live-browser-identities)
for password-free native authorization and personal sign-in handoffs. [Codex device auth](https://developers.openai.com/codex/auth)
requires account/workspace permission. [Cursor auth](https://cursor.com/docs/cli/reference/authentication)
is separate from app presence. A login-status line or credential file is
insufficient: every harness must answer a real request without tool calls.

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
`.claude/.credentials.json`, `.codex/auth.json` and the browser identity store
`.yoke-browser-identities` are excluded from the golden and kept live on every
reset, so a reset never puts back a rotated token or cookie. If a previous golden exists, reset first, then make
the operator preparations above and re-save. The first bare home needs no
Yoke installation before capture. Never seal a home containing Yoke residue.
Choose a new absolute destination outside the test home, preferably a sibling
of its current golden; do not overwrite a saved baseline:

```text
yoke test-machine golden-capture --project P --machine NAME --destination /Users/Shared/yoke-golden/TESTUSER-home-DATE
```

Read `--help` for default destination and custom probes. Probes run in the GUI
Terminal context. A failed capture does not replace the registered baseline.
The captured directory, `.manifest` and `.probes` stay private on the host.
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
copies of preserved entries are never restored; a present declaration must match
and every declared entry must be absent from the golden. Recapture a golden
saved before the list included the harness logins so it carries none.
Only the dedicated test home is captured; system settings/other homes are not.

| Named refusal | Recovery |
| --- | --- |
| `golden_capture_yoke_residue` | Return to the existing baseline, then prepare and save again |
| `golden_capture_foreign_owner` | Diagnose the unexpected owner's writer; prove a product-owned restoration path before capture |
| `golden_capture_preserved_state_invalid` | Inspect the named OS entry's owner/type or symlink ancestor; preserve content and do not change its owner |
| `golden_capture_destination_occupied` | Choose a new destination |
| `baseline_probe_failed` | Read cause/reason/recovery: the probe names `probe_executable_missing`, `probe_request_timed_out`, `probe_launch_failed`, `probe_harness_exit_nonzero`, `probe_reply_unanswered` or `probe_check_unmet`; `probe_exit_undeclared` means the golden predates the cause table, so recapture it |
| `baseline_probe_bridge_unavailable` | Repair the named bridge condition, then retry |
| `golden_capture_copy_home_failed` | Read bounded copy diagnostics; repair the named path, save to a new destination |

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
clears product residue, restores content/modes, and runs sealed probes. The
restore merges each captured directory into place with `ditto`, so a macOS
daemon recreating its directory mid-restore does not fail it. Restoring a home
cannot restore an external grant; a login that expires on the live host is
fixed by signing in again in the GUI, with no recapture. Recheck screen saver 0 and
the GUI keychain after the roundtrip, with Screen Sharing disconnected.

Require passing operation receipts bound to the new golden, standard checks,
and real desktop/input evidence. If authentication expires, the operator signs
in in the GUI and proves it; the next reset keeps that login. Never recapture a mixed home
after a failed restore. Capture then verify/reset is one ordered saved-state
proof; an old receipt or a successful capture alone cannot replace it.

## 11. Live browser identities

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

Use the logged-in, unlocked test-user desktop through Screen Sharing and the
GUI Terminal context; the login keychain remains that user's.
