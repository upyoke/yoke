# macOS baseline capture and recovery

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > macOS baseline recovery
<!-- /yoke:breadcrumbs -->

Complete [macOS host provisioning](macos-host-provisioning.md) first.

## 8. Harness sign-in and acceptance set

Sign the operator identity (the project's browser-control `default_identity`)
into `https://app.upyoke.com` (or the declared self-hosted app URL) once with
`yoke browser authorize --project P --identity NAME --test-machine NAME`.
The remote command can open a viewer on the controller. To keep the window
on the fixture, run `yoke browser authorize --project P --identity NAME
--declarations-json "$DECLARATIONS"` directly in the test user’s GUI Terminal.
Use the browser-control `settings_json` from the project’s capability settings
and keep it private. Complete password and MFA, then close the authorization
window so Yoke checks both Google and the app. Later approval should need only
an existing account pick.
Start each harness's vendor login flow from the test user's **GUI Terminal**;
the operator types passwords only where asked. Open one sign-in window at a
time and wait for the operator to confirm before opening the next. Follow the
[browser identity procedure](#11-live-browser-identities)
for password-free native authorization and personal sign-in handoffs. [Codex device auth](https://developers.openai.com/codex/auth)
requires account/workspace permission. [Cursor auth](https://cursor.com/docs/cli/reference/authentication)
is separate from app presence. A login-status line or credential file is
insufficient: every harness must answer a real request without tool calls.
Open Claude for Mac as the test user, finish its first-run prompts, sign in,
and quit it normally. The Mac golden probe opens the native app and quits it;
it never clicks or types. It decides signed-in from the app's own stored
session, an unexpired claude.ai `sessionKey` cookie read by name and expiry
only: with it, any rendered window that stays off the first-run and Sign In
screens for five seconds passes, whatever the sidebar says. Without a readable
session it falls back to the signed-in Chat, Code or Cowork sidebar markers.
The first-run and Sign In screens, or a session the app dropped while it ran,
fail `probe_check_unmet` (sign in again). Any other window fails
`probe_layout_unrecognized`: do not sign in again or recapture; report the app
version as a Yoke defect. It leaves screen text and images on the fixture only
for the duration of the check. For other
desktop surfaces, verify Codex in the ChatGPT app and Cursor independently
after the golden reset.

After harness sign-in, run `yoke test-machine golden-capture` (section 9)
to prove real requests and recapture. Identity sign-ins stay live outside goldens.

From the dedicated test user's GUI Terminal, run
`cd ~ && claude --dangerously-skip-permissions` once. If Claude asks whether
to trust the folder, choose **Yes, I trust this folder** for the test home.
If macOS asks whether Terminal may access the test user's Desktop folder,
allow it on the fixture. Accept Claude's dangerous-mode prompt and confirm
Claude shows bypass permissions on. Quit the interactive session.
Require `skipDangerousModePermissionPrompt=true` in
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
baseline preparation path. Remove the installed `yoke-global` skill and its
Claude discovery link from the dedicated fixture before capture. Other skills
stay in place. If reset reports Yoke residue inside the golden, prepare and
register a clean replacement before running another reset.

Harness logins themselves are never captured: the
login Keychain (`Library/Keychains`, holding Claude's and Cursor's CLI logins),
`.claude/.credentials.json`, `.codex/auth.json`, the native Claude profile
`Library/Application Support/Claude`, and `.yoke-browser-identities` stay live
outside the golden. Restore skips captured copies of these paths even on an
older golden. Capture a new baseline to seal the current native Claude desktop probe.
The identity profiles are the machine's only saved browser logins. Chromium writes
a profile's cookies as it closes, so capture and reset first find each
identity browser's main process with `/bin/ps`, send it SIGTERM (Chromium's
clean shutdown) and wait up to 30 seconds; they never force-quit it. If a previous golden exists, reset first, then make
the operator preparations above and re-save. The first bare home needs no
Yoke installation before capture. If browser authorization used a temporary
Yoke install with no universe or registered projects, run
`yoke uninstall --projects none --yes` as the test user. Check the deferred
uninstall log for `CLI: done` and require the launcher to disappear. An
`uninstall_backup_not_applicable` refusal means omit the backup flag. If
`cli_release_in_use` occurs, identify the process holding the release lease
with `lsof`, stop the owned command or service, and retry. Clear the Yoke and
uv paths named by capture while preserving the live browser identity and
harness state. Never seal a home containing Yoke residue.
On the host, create a private parent directory outside the test home for each
attempt. Retention can delete unregistered siblings. Pass a new child path
inside that existing directory and preserve old or failed captures and sidecars.

```text
yoke test-machine golden-capture --test-machine NAME --destination /opt/yoke-golden-DATE-UNIQUE/home
```

Read `--help` for default destination and custom probes. Probes run in the GUI
Terminal context. A failed capture does not replace the registered baseline.
The captured directory, `.manifest`, `.probes` and `.harness-clis` stay private on the host.
Golden capture records each CLI's version beside the golden in
`GOLDEN.harness-clis`. Before a QA plan's first reset on this host, Yoke
compares those versions with each vendor's latest release; when one is newer
it resets, installs the newer CLIs with each vendor's installer as the test user and
captures a new golden under the plan's own host lease. Do not hand-update
CLIs for QA; a failed refresh stops the plan with the step to repair. A hand
capture whose CLIs are behind warns `golden_harness_clis_behind_latest` and names
each one, because the next QA plan replaces that golden with a refreshed one.
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
An entry kept only since the golden was sealed stays inert in it and the live
copy is kept. macOS also keeps the generated CoreSpeech `speakerRecognition`
and `secondPassChecker` directories under its `onDeviceCompilationCaches`
folder live. macOS 27 denies opening these artifacts even with Full Disk
Access. Capture and reset leave them in place and verify that each present
cache is a real directory owned by the fixture account.
The historical per-user `Library/Application Support/com.apple.TCC`
directory stays live when present. Some fresh macOS 27 accounts have no such
directory. Verify Full Disk Access and the Terminal bridge directly. Only the
dedicated test home is captured.

| Named refusal | Recovery |
| --- | --- |
| `golden_capture_yoke_residue` | Remove the named path as the test user, or reset to the registered golden when `yoke test-machine get` shows `golden_baseline_path`; then capture again |
| `golden_capture_foreign_owner` | Diagnose the unexpected owner's writer; prove a product-owned restoration path before capture |
| `golden_capture_preserved_state_invalid` | Inspect the named OS entry's owner/type or symlink ancestor; preserve content and do not change its owner |
| `golden_capture_destination_occupied` | Choose a new destination |
| `test_machine_sign_in_app_quit_not_proved` | An identity browser still runs 30 seconds after SIGTERM. Close its windows on the machine yourself, answering any prompt it shows, then retry; never force-quit it |
| `test_machine_sign_in_app_probe_failed` | Yoke could not list the identity browser processes over SSH. Check SSH to the machine, then retry |
| `baseline_probe_failed` | Read cause/reason/recovery and sanitized native exit diagnostics. Nonzero execution retains its category; reason/recovery names quota, authentication, model or transport evidence. Quota waits for provider capacity; only diagnosed auth calls for sign-in. Preserve the golden and failed capture; never reset credentials to clear quota |
| `baseline_probe_bridge_unavailable` | Repair the named bridge condition, then retry |
| `test_machine_reset_console_user_mismatch` | Another account owns the console, so reset quit nothing. Log the test user in at the console, log other accounts out, then retry |
| `test_machine_gui_app_list_failed` | `lsappinfo list` failed or showed no GUI session, so reset cannot find leftover apps. Check SSH and that the test user is logged in at the console, then retry |
| `test_machine_gui_app_quit_not_proved` | The named app survived its quit and a forced kill. Quit it at the console with Activity Monitor, then retry |
| `test_machine_terminal_relaunch_failed` | The home was restored but Terminal opened no window. Open Terminal at the console, then run `yoke test-machine bridge-diagnose` |
| `test_machine_gui_app_probe_failed` | Yoke could not read whether the named app runs. Repair SSH to the machine, then retry |
| SSH times out right after a GUI-app quit | The host dropped off the tailnet. Relaunch Tailscale at the console, confirm `tailscale status` shows the host online, then retry the reset |
| `golden_capture_copy_home_failed` | Read quoted `copy_stderr`; repair its reported cause, then save to a new destination. Copy tools use `LC_ALL=en_US.UTF-8` so SSH caller locales do not cause warnings |

Never discard copy errors, change a sealed manifest, or make the golden
writable to force acceptance. Live destination ACL/mode preparation is the
registered reset's responsibility; partial clear/copy is a failed operation.

## 10. Prove the saved state and restore it

These commands are **destructive**, deliberately authorized provisioning work:

```text
yoke test-machine verify --test-machine NAME
yoke test-machine reset --test-machine NAME --baseline fresh-host
yoke test-machine get --test-machine NAME
```

Read their `--help`. Verify reaches both baselines and ends `shell-preconfigured`
with the current Yoke launcher installed. Reset reaches one baseline;
`fresh-host` returns the clean signed-in home, not a blank user. The operation
retains live SSH, privacy and harness-login state, stops owned services/writers,
clears product residue, restores content/modes and runs sealed probes, with
the controller's current standard probes in place of older sealed ones (sealed
extra probes still run; evidence `standard_probes` names both digests). Before
the restore it lists the test user's foreground apps with `lsappinfo list` and
quits every one except Finder, the identity browsers (already closed with
SIGTERM), Docker Desktop (stopped by the self-host teardown) and Tailscale
(the reset's own SSH runs over its tunnel, so quitting it would cut the reset
off from the host), matched by bundle ID; evidence `gui_apps_kept` names them. An app held open by a sheet has its process tree killed; evidence
`gui_apps_quit` records each app as `graceful` or `forced`. Terminal is quit
the same way, and after restore it relaunches without saved windows to avoid
probe stalls. A Claude desktop probe that cannot quit the app it opened fails
`probe_app_quit_blocked`: a previous session left the app open, so run
`yoke test-machine reset` rather than reinstalling it.
The restore merges each captured directory into place with `ditto`, so a macOS
daemon recreating its directory mid-restore does not fail it. Restoring a home
cannot restore an external grant. A login that expires on the live host is
fixed by signing in again (`yoke browser authorize --test-machine` for a
browser identity); the kept-live login survives the next reset, and `yoke test-machine golden-capture` saves the rest of that signed-in
state into the baseline. Reset refuses `test_machine_sign_in_app_quit_not_proved`
before clearing when an identity browser will not close. Recheck screen saver 0 and
the GUI keychain after the roundtrip, with Screen Sharing disconnected.

Require passing operation receipts bound to the new golden, standard checks,
and real desktop/input evidence. If authentication expires, agents rerun the
GUI login (the operator types only the password) and save it with
`yoke test-machine golden-capture`; the next
reset keeps that login. Never recapture a mixed home
after a failed restore. Capture then verify/reset is one ordered saved-state
proof; an old receipt or a successful capture alone cannot replace it.

## 11. Live browser identities

Run `yoke browser authorize --test-machine NAME` to check each identity. It
opens tabs only for expired sites and names the account to use. The identity
profiles are the machine's only saved login store and stay live through
reset; there is no Safari sign-in. Confirm release-matched help and operation
receipts before relying on an installed release. Before running it, read the
complete [machine sign-in](browser-identities.md#machine-sign-in-and-approval)
procedure.

1. Apply the project-owned sign-in policy. The human only types their own
   password or credential; agents complete every other prompt.

Before sign-in, follow the complete [macOS sign-in
procedure](browser-identities.md#macos-sign-in-procedure).

## Add per-machine QA plans

After registration and the saved-state proof, use `yoke qa plan create --help`
and `yoke qa plan-cases --help` to build deterministic checks and exploratory
missions for the new machine. Bind each to its machine name and select cases
its OS and architecture support. Where the host meets the local-mode minimum,
require successful embedded PostgreSQL startup. Prove the current Cursor CLI
with a real request. Start install coverage on `fresh-host`. Checks that
require an installed CLI start their own `shell-preconfigured` chain when
`starting_state_lacks_yoke` blocks a clean-host plan. Attach each plan with
`yoke qa item-plan attach --help`.
