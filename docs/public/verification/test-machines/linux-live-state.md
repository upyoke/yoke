# Linux live harness installations and reset recovery

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Verification](../index.md) > [Machine QA](index.md) > Linux live state
<!-- /yoke:breadcrumbs -->

Install Claude, Codex and Cursor as the dedicated test user using the supported
installers in [Linux provisioning](linux-host-provisioning.md#3-harness-installation-and-sign-in).
Keep `.local/bin` on both login and SSH PATH. Require a real request from all
three before restoring the clean baseline. Sign-ins and installations stay
live; never put their current state into a golden to repair a failed request.

## What survives

Reset renames these live entries out of the home before clearing and restores
them afterward with their modes, using the same mechanism as native Chromium:

- `.claude/.credentials.json`, `.codex/auth.json`, `.config/cursor/auth.json`

- `.local/bin/claude`, `.local/share/claude`
- `.local/bin/codex`, `.local/lib/node_modules/@openai`, `.codex/packages`
- `.local/bin/agent`, `.local/bin/cursor-agent`, `.local/share/cursor-agent`
- `snap/chromium/common/chromium`

Capture omits these entries; reset ignores stale copies in older sealed
archives. Working CLI links must resolve inside the preserved home installation
roots, with test-user-owned entries and regular parent directories. Other
`.local` content, including Yoke and uv products, still follows clean-baseline
rules. Keep vendor runtime prerequisites outside the home baseline.

Use the standard registered Yoke setup permission pass for every detected
harness after installation, as taught by [Codex on Linux](codex-on-linux.md).
Do not edit individual harness permission files to imitate that pass.

## Interrupted reset

Keep the normal host lease. Through `test_machine.exec`, identify the exact
remote archive process by test-user UID, reset operation, home and sealed
baseline path. A local timeout or SSH exit does not prove remote exit. Wait for
it, or stop only that verified process when authorized; prove it exited before
another reset. Read the native process state and storage diagnostics. Disk
sleep or I/O pressure alone does not prove a broken archive or missing install.

Never reset, capture or clean recovery stashes while that process may be alive.
An interrupted restore can temporarily remove executables and native
credential files before moving the live entries back.

Finish the interrupted restore through `test_machine.exec` under explicit
repair authority: identify each retained live login stash by its native store
structure without printing contents; move it back to that harness's native
location with its original mode; compare digests. Keep every stash until proof
passes. A restored credential is not a new sign-in.

Recover retained Chromium or installation entries to their absent native paths
without overwriting another live entry. New `yoke-live-home-*` stashes retain
home-relative names; older Chromium stashes use `profile`, and older sign-in
stashes use `store`. Preserve them when provenance is ambiguous; ask the
operator before selecting between competing live copies.

Run each sealed real-request probe again. Only a restored live credential that
still reports expired/sign-in-required needs a vendor login in which agents
drive every step and the operator types only their password. Name that harness,
machine and test user; preserve the golden. Quota and transport failures use
their diagnosed recovery, with no credential reset or golden capture.

Finally run `test_machine.reset` for `fresh-host` and inspect its entire receipt:
all three real requests pass, working executable links survive, Chromium stays
live and product absence is proved. `test_machine.verify` is destructive and
also visits `shell-preconfigured`; finish with `fresh-host` when that is the
required state. The CLI help owns the full invocation and lease rules.

## Named-machine audit

On linux-lab, 2026-10-18, an interrupted reset left native Chromium and live
credential stashes outside a partly restored home. Restoring the uniquely
identified Chromium profile preserved its cookie digest. Restoring Claude and
Codex live stashes, while keeping the old sealed copies privately, changed both
real requests from expired OAuth failures to passes; Cursor also passed.
The reset process had exited before recovery, and no credential contents were
printed. The completed installation-preserving `fresh-host` reset passed all
five sealed checks, including the three real requests, at 04:07 UTC. Its
receipt listed all live installations, sign-ins and Chromium as preserved,
including Codex helper packages; Yoke and uv were absent in both shell contexts.
Live installation roots and Chromium retained their original inodes.
The earlier SSH exit code 255 had no retained causal diagnostic in kernel,
SSH or session logs; the same host-key warning occurred on successful checks.
Preserve that uncertainty rather than treating the warning as a cause.
