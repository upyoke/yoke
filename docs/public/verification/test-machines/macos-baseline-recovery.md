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
For fixtures covering the desktop surfaces, also open Claude, Codex in the
ChatGPT app, and Cursor as the test user. Finish each app’s first-run prompts
and verify the signed-in account. Keep desktop and CLI checks separate, and
verify each required desktop sign-in again after the golden reset.

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
baseline preparation path. Harness logins themselves are never captured: the
login Keychain (`Library/Keychains`, holding Claude's and Cursor's logins),
`.claude/.credentials.json`, `.codex/auth.json` and the browser identity
store `.yoke-browser-identities` are excluded from the golden and kept live on
every reset, so a reset never puts back a rotated token or cookie. The
identity profiles are the machine's only saved browser logins. Chromium writes
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
Choose a new absolute destination outside the test home, in a separate new parent for EACH attempt; retention can
delete unregistered siblings. Preserve old/failed captures and sidecars:

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
copy is kept.
Only the dedicated test home is captured; system settings/other homes are not.

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
yoke test-machine verify --test-machine NAME
yoke test-machine reset --test-machine NAME --baseline fresh-host
yoke test-machine get --test-machine NAME
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
