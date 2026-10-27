# macOS baseline capture and recovery

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Verification](../index.md) > [Machine QA](index.md) > macOS baseline recovery
<!-- /yoke:breadcrumbs -->

Complete [macOS host provisioning](macos-host-provisioning.md) first.

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
Choose a new absolute destination outside the test home, in a separate new parent for EACH attempt; retention can
delete unregistered siblings. Preserve old/failed captures and sidecars:

```text
yoke test-machine golden-capture --project P --test-machine NAME --destination /opt/yoke-golden-DATE-UNIQUE/home
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
An entry kept only since the golden was sealed, such as Safari's cookie store,
stays inert in it and the live copy is kept.
Only the dedicated test home is captured; system settings/other homes are not.

| Named refusal | Recovery |
| --- | --- |
| `golden_capture_yoke_residue` | Remove the named path as the test user, or reset to the registered golden when `yoke test-machine get` shows `golden_baseline_path`; then capture again |
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
yoke test-machine verify --project P --test-machine NAME
yoke test-machine reset --project P --test-machine NAME --baseline fresh-host
yoke test-machine get --project P --test-machine NAME
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

The remote `--test-machine NAME` command includes both checks by default; there
is no desktop opt-out. Confirm release-matched help and operation receipts
before relying on an installed release. Before running it, read the complete
[desktop browser checks](browser-identities.md#desktop-browser-checks) procedure.

1. Apply the project-owned sign-in policy. The human only types their own
   password or credential; agents complete every other prompt.

Before sign-in, follow the complete [macOS sign-in
procedure](browser-identities.md#macos-sign-in-procedure).
