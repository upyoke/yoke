# Linux baseline capture and recovery

Complete the [Linux host procedure](linux-host-provisioning.md) through desktop
and identity acceptance before capturing a clean baseline. This procedure owns
the capture, reset roundtrip and sealed-state recovery that follow.

## 6. Clean home, standard checks and capture

If a current golden exists, reset to it before refreshing signed-in fixture
state. If step5 temporarily installed Yoke, return to the clean existing
baseline after sealing the separate profile. For a first bare home, keep Yoke
absent before saving; registering/capture runs from the QA workstation.
Do not manually capture a partially cleared home or bake Yoke/uv state into it.

Acceptance requires steps 1–4 plus all native harness real requests, Claude
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
never captured and are preserved on restore. Desktop Chromium sign-ins must
also stay live outside golden snapshots: preserve the existing snap store
`~/snap/chromium/common/chromium` only when present, and never restore stale
sign-in state from an older golden. Require a reset receipt and real browser
sign-in proof against the selected release; this procedure alone is not that
proof. No archive or auth material enters QA artifacts, settings or source control.

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
on login and SSH shells. It preserves live SSH and terminal preference while
restoring settings/history from the golden.

Capture and reset first ask a running desktop Chromium to quit (SIGTERM, which
saves its cookies) and wait up to 30 seconds; it is never force-killed. One
that stays open refuses `test_machine_sign_in_app_quit_not_proved` before
anything is copied or cleared. This flushes the live browser store before
preservation; its sign-in state must not come from the restored archive.

Harness sign-ins are never rolled back. The login files
(`~/.claude/.credentials.json`, `~/.codex/auth.json`,
`~/.config/cursor/auth.json`) are left out of every captured golden and kept
live through reset with their own modes; the receipt lists each present one in
`preserved_entries`. A copy an older golden sealed is never restored. A failed
login is repaired by signing in again on the host; no recapture is needed. OS package
fixture journals outside the home are separate and may reverse mission changes;
permanent desktop tools must remain baseline.

## 8. Recovery without changing the seal

| Refusal | Required recovery |
| --- | --- |
| `linux_desktop_stop_not_proved` | Repair termination of the named fixture desktop, then retry; other users are excluded |
| `test_machine_sign_in_app_quit_not_proved` | Close every Chromium window on the fixture desktop, answering its prompts, then retry; `reason` names the helper's own refusal |
| `linux_preserved_home_entry_unsafe` | Make the named live entry (a login file or harness installation) and its parents regular paths owned by the test user, then retry; the home was not cleared |
| `linux_home_writers_stop_not_proved` | Stop the named test-home writer through its owner, then retry the sealed baseline |
| `linux_golden_home_clear_failed` | Read refused entry, resolve writer/ownership, retry; never seal the mixed home |
| `baseline_probe_failed` | Read cause/reason/recovery and sanitized native exit diagnostics. Quota waits for capacity; transport retries after recovery; only diagnosed auth calls for sign-in. Preserve the golden and failed capture; never reset credentials to clear quota |
| `linux_golden_operation_timeout` | Capture/restore allows20minutes; disconnect does not prove remote exit. Stop or wait for that process before retrying |

A timeout may leave unregistered archive/manifest or a partly restored home.
Inspect only the named destination/capture temporary paths after remote exit;
use a new capture destination or retry the existing sealed restore. Never use
an unsealed archive or edit its manifest to force acceptance. Expired sign-in
requires operator login and a passing real request; keep it live without recapture.
[Live-state recovery](linux-live-state.md) owns installations, exclusions and repair. A successful save alone is not a
proved roundtrip.
