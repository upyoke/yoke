# Golden baseline semantics

Preparing, signing in, saving, restoring and repairing a Test Machine has one
complete ordered procedure per OS in the Machine QA Pack:

- [macOS](../../packs/machine-qa/versions/1.3.25/files/docs/packs/machine-qa/macos-host-provisioning.md)
- [Linux](../../packs/machine-qa/versions/1.3.25/files/docs/packs/machine-qa/linux-host-provisioning.md)
- [Windows/WSL2](../../packs/machine-qa/versions/1.3.25/files/docs/packs/machine-qa/windows-host-provisioning.md)

The [provisioning index](../../packs/machine-qa/versions/1.3.25/files/docs/packs/machine-qa/host-provisioning.md) installs
as `docs/packs/machine-qa/host-provisioning.md`. This page explains the model
behind its evidence, without providing a second preparation procedure.

`fresh-host` is user-equivalent: vendor harnesses and their signed-in fixture
state remain available while Yoke state and launchers are absent.
`shell-preconfigured` adds the current Yoke shell launcher. Baseline identity
therefore matters independently of the operation's success flag.

The sealed home lives outside the restored home. Its manifest binds identity,
size/digest and probe document; modes and ACLs remain part of captured state.
macOS capture excludes the exact root:wheel regular audiovisual preference
`Library/Group Containers/group.com.apple.secure-control-center-preferences/Library/Preferences/group.com.apple.secure-control-center-preferences.av.plist`.
The shared preservation contract validates its owner/type and rejects symlink
ancestors, records the exclusion in the sealed manifest, and keeps the live
entry during reset alongside SSH access, user TCC, the live harness logins
(the login Keychain `Library/Keychains`, `.claude/.credentials.json` and
`.codex/auth.json`), the browser identity store and Safari's cookie store
(`Library/Containers/com.apple.Safari/Data/Library/Cookies`).
`PRESERVED_HOME_ENTRIES` is the one declared list; capture prunes every entry
on it, the manifest seals it as `preserved_home_entries`, and a reset keeps
each one live, requiring only SSH access and user TCC to be present. A restored
login or cookie would be the golden's rotated one. Every other foreign entry
still refuses. Older manifests remain readable and their captured copies of
preserved entries are never restored; a present declaration may name only kept
entries and the entries it declares must not be captured. An entry kept only
since the seal is inert in that golden.

Safari writes its cookie store when it quits. macOS capture and reset first ask
a running Safari to quit and wait for it to exit
(`yoke_harness.ssh_mac_sign_in_apps`); they never force-quit it, and refuse
`test_machine_sign_in_app_quit_not_proved` before copying or clearing when it
stays open. Only pgrep's "no match" exit means Safari is not running; any other
exit, such as an SSH failure, refuses `test_machine_sign_in_app_probe_failed`
with the probe's exit code, stderr and recovery.
The archive is private fixture material, not a QA artifact. Whole-home content,
CLI liveness, persistent OS grants and the actual visible desktop are separate
proofs: a passing one cannot establish the others.

macOS capture omits sockets and FIFOs while retaining resource forks, extended
attributes, ACLs and file flags. Its tar stream carries extended attributes in
AppleDouble metadata rather than duplicate PAX xattr headers: sandbox container
attributes can exceed the tar reader's 1 MiB special-header limit. Any copy
error still fails capture and reports its path and message in the receipt;
partial destinations cannot be registered as a baseline.

The probes seal reports upload and chmod failures separately in the existing
`golden_probes_seal_failed` refusal. It retains the sidecar path, sub-step,
exit code and bounded remote stderr; transport exceptions name their type
when no exit status exists. Recovery preserves the failed capture and calls
for repairing the named access or SSH failure before using a new destination.
macOS chmod receives its option delimiter before the mode, so it cannot mistake
the delimiter for another file and report failure after sealing the sidecar.

Restore cannot govern objects outside the home merely by copying files.
Product-owned Compose resources, running home writers, service-manager jobs
and declared temporary residue have independent ownership/absence checks.
Compose labels protect unrelated workloads; PID start times protect reused
process ids; service inventory checks protect against deleted definitions whose
jobs remain loaded. A failed prerequisite preserves its diagnostic in the
operation receipt, and a partial restore cannot establish a new baseline.
On macOS a booted iOS Simulator device is such a writer: it runs from the
home's CoreSimulator device set and repopulates it through the clear, so the
reset reaps its device tree first. Other macOS daemons keep running and can
recreate their directory while the restore copies it, so each captured
directory is merged into place with `ditto` rather than created by `cp -R`,
which would stop on `File exists`. A restore that stops names each unrestored
entry with a bounded, printable excerpt of its copier stderr
(`restore_state.entry_errors`), because the scratch log holding that stderr is
removed when the reset program exits.

Linux golden capture proves its own reset roundtrip and sealed probes, starts
the fixture desktop through xrdp, validates a non-blank screenshot, and ends the
session before registration. Its receipt names the failing step when any check
fails. Desktop discovery counts active logged-in fixture users, excluding
greeters, closing sessions and other users. Reset ends the fixture desktop.

Before it writes, capture compares free space on the destination filesystem
with the home's file bytes. `golden_capture_insufficient_space` names that
parent and the recovery: remove every other snapshot there, keep each
project's registered golden for this machine (`yoke test-machine get` shows
`golden_baseline_path`) and their `.probes` and `.manifest` files, then retry
`yoke test-machine golden-capture`. A check that cannot read the home or the
filesystem refuses `golden_capture_space_check_failed` instead of a traceback.
After the new golden is registered, capture deletes retired snapshots beside
it. A parent directory named for the test user is that user's golden root, so
every other child goes, including dated homes, mixed captures, `.yoke-golden-*`
temporaries and retired browser profiles. A shared parent deletes only this
user's `USER-home-*` and `home-*` snapshots, so another user's baseline stays.
One machine can be registered in several projects that share a golden parent.
The capture result's `kept_golden_paths` names every project's registered
golden for this machine in that parent, and each one stays with its sidecars;
only snapshots no project registers are deleted. A symlink is left in place.
`golden_snapshot_retention_failed` means the new golden is already registered
and the named leftovers are still there; remove them, keep every project's
registered golden, and do not capture again until they are gone. When the
server cannot name the other projects' goldens (`kept_golden_paths` absent or
`kept_golden_paths_unknown` set), nothing is deleted and the refusal says why. Windows/WSL capture uses this same Linux archive, so the
same check and retention apply there.

Linux user-service mutations share the relay's 180-second operation budget;
inventory probes retain a 30-second limit. Timeout receipts name the command
and unsettled job. Archive failures preserve bounded, redacted native exit,
stdout and stderr through mission preparation, including malformed receipts.

The SSH access needed to finish restore remains live. Linux/WSL reset never
rolls a harness sign-in back (`yoke_harness.ssh_linux_sign_in_stores`). Before
clearing, it runs the sealed `Claude real request`, `Codex real request` and
`Cursor real request` probes against the live home. Each verified login is
carried forward over the restore with its own mode. A failing login restores
from the golden only when it has not changed since the seal; otherwise the
reset refuses `test_machine_sign_in_newer_than_baseline` before clearing, naming
the store, the probe and its diagnosed reason/recovery. The outer refusal
retains quota or transport recovery instead of substituting sign-in advice.
The newer-store guard uses file modification time; it does not establish who
wrote the store or prove a new human login. Linux capture and reset first ask a
running desktop Chromium to quit and wait for it to exit
(`yoke_harness.ssh_linux_browser_approval`), the same rule macOS applies to
Safari, refusing `test_machine_sign_in_app_quit_not_proved` before copying or
clearing when it stays open. Windows state and WSL registration remain
outside the Linux home.

A completed sign-in on any test machine is saved at once with
`yoke test-machine golden-capture`: it proves the real requests, quits Safari
on macOS or the desktop Chromium on Linux and seals a new baseline, so no later reset rolls the sign-in back.
Only a diagnosed authentication failure or an unmet baseline setting calls for
repairing that state; a generic native failure does not establish a login problem.

A reset or capture receipt names what failed. Each check row's `name` and `ok`
belong to the operation, never to nested evidence. A failed macOS reset keeps
the first error code: a later failure, such as removing the uploaded reset
program, never replaces it. Its `failed_calls` evidence lists every failed call
(`preclean`, `upload`, `mode`, `reset`, `cleanup`) with its exit code and
bounded stderr, or the exception type and message. Exit 124 is the runner's own
SSH failure (timed out or could not start), reported as
`test_mac_reset_transport_failed`; the host may be fine, so check the
executing machine's SSH access before repairing the host. When the server still
refuses a receipt, `test_machine_operation_submit_failed` repeats the host's
own error code, reason and recovery, because the refused receipt is not
recorded anywhere else.
System packages remain outside home-only restoration and may additionally be
owned by a mission fixture's package journal.

Structure is not liveness: a captured credential may expire. Canonical
standard per-OS probes are sealed with every new capture, alongside extra
checks. A named harness check requires a tiny native request; status-only
output and credential-file presence are insufficient. Output stays on the
host, while readiness records retain classified cause, reason and recovery.
Each sealed standard probe exits with a code from one table
(`yoke_harness.baseline_probe_failure_causes`) that the classifier reads back:
executable missing, request timed out, launch failed, unknown harness non-zero
exit, unanswered reply, check unmet, or a diagnosed native refusal. Explicit
native error envelopes and fixed error phrases distinguish exhausted quota,
authentication rejection, model rejection, transient transport failure and
request throttling. A Claude weekly-limit error remains quota exhaustion even
when the native exits nonzero and also reports `rate_limit`. Quota recovery
waits for the provider window or restored plan capacity; transport and throttling
recovery checks the service and retries after recovery. These causes never
advise sign-in, resetting credentials or recapturing a baseline. Authentication
advice requires native authentication evidence. Unknown failures remain unknown
and direct the operator to local diagnostics while preserving the golden.
No failure defaults to "not signed in", and
`expectation_met` is null when nothing was expected.
An unanswered reply is one the shared reply parser rejected while the harness
exited 0. Nonzero native exits also keep a sanitized `reply_rejection` record,
including the original native exit code; the sealed exit code retains the
native diagnosis. Receipt `cause` stays `probe_harness_exit_nonzero` for these
execution failures; `reason` and `recovery` retain the specific diagnosis.
Cursor workspace trust keeps its distinct existing refusal cause.
The parser prints only this record; raw native output stays on the host.
It holds the rejection branch,
the stream's event types in order, the final event's shape, the booleans
`exact_ok_reply`, `tool_use` and `degraded_context` (lines that were not JSON
events), and the harness exit code. It never holds reply text, account output
or a transcript. Cursor ask mode cannot disable tools. A Cursor `tool_call`
whose payload is only a read, grep, list, or glob inspection does not reject
when the final result is success and the reply is exactly OK. Write, shell,
and any other tool call still reject. `tool_use` stays true on a rejection
record whenever a tool call was present. The failed probe row keeps the record, so an operator-run
reset or verify returns it in its result. A QA run whose baseline rejected a
reply stores each record as a `probe_reply_rejection` JSON artifact and names
the branch, diagnosed reason and recovery in its verdict reason. A golden sealed
before these records returns none; its reason says so and directs inspection
of native diagnostics on the host. Preserve failed captures and retry only after
the diagnosed cause is repaired; failed probes never seal or pass.
An undeclared nonzero exit is retried exactly once before `baseline_probe_failed`;
evidence retains the first attempt as `retrying`. Declared causes, unmet
expectations and unavailable bridges fail immediately. A repeated
`probe_exit_undeclared` calls for recapturing the golden with current probes.
An undelivered bridge probe is distinct from a program that ran and refused.
Older sealed sidecars remain historical state, not implicit inputs to a new
capture's required check set.

The separate browser-profile seal belongs to a different component from
the clean home. It binds the private profile to its project/user/home and is
outside ordinary home restoration. Its archive receipt establishes identity
and integrity; signed-in application UI remains an independent proof.

[Operation contracts](test-machine-operations.md) cover leases and receipts;
[testing and verification](../testing-verification.md) covers QA verdicts.

## Yoke application sign-ins

Yoke's hosted machine-connection tests use an account able to approve a test
machine in the application paired with their plan's bound environment.
The installed `installer-campaign` plan is bound to Production and uses
`https://app.upyoke.com`. Its source template is projected onto that one plan
target; source labels are not separate environment branches in a test.
No installed machine case requires a Stage application sign-in. Installing
wheels and reaching a browser wait screen alone do not need an application
sign-in. These are Yoke test facts, not Machine QA Pack prerequisites.

Yoke's agent-driven walker case restores the separate saved profile after
candidate installation and uses it for its own fresh machine approval. The case
instructions own pages, paths, labels, controls, refusal text and completion
checks. Its existing retained host-command keeps the candidate terminal alive;
`yoke qa browser setup` and `yoke qa browser step` drive candidate Chromium one
observed step at a time. Read those commands' `--help` before execution. Do not
add an approval command or extend the scripted terminal recipe contract.
Follow the Machine QA Pack's [setup responsibilities](../../packs/machine-qa/versions/1.3.25/files/docs/packs/machine-qa/setup-responsibilities.md).
Agents complete every software-capable setup step and system permission prompt.
Only browser sign-in and OS permissions that software cannot grant need the
operator. Product code alone enters passwords from stored secrets; nobody types
them by hand. Verify a fresh authorization link belongs to this execution and
the visible signed-in identity is the intended test account before clicking.
Actual candidate application UI and terminal completion are separate proofs
from the snapshot seal. Scripted terminal cases keep their current route.
The proven Mac Safari route remains in place until the walker has completed a
real test-mac approval.
