# Deployment plan execution

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Deployment plan execution
<!-- /yoke:breadcrumbs -->

The holder runs item cases and single-member plans with their pinned stage:

```text
yoke qa plan run --item PREFIX-N --stage STAGE --project P
```

A post-deploy plan shared by two or more release members at item QA entry runs
once per release as one driver-owned
[plan group](#plan-groups):

```text
yoke qa plan run --deployment-run-id RUN --stage item-qa --plan PLAN --project P
```

See [item recovery](failed-item-qa.md) and `yoke qa plan run --help`.

Admission copies executable item cases, retaining others on the item. Attached
plans supply cases without copies; stage targets supply `target_env` for corrections.

[QA continuity](deployment-qa-continuity.md): item authority, release takeover,
cross-build observations and exact-execution recovery.

## Plan groups

At `item-qa` entry, one attacher makes member QA; two or more make a driver-owned
group. Later attachments keep that ownership. A sole attacher a closed group in
the run's lineage already covered stays with that group and owes no new rows.
Once a plan is a group, members' never-run own rows of it are retracted as
`replaced by plan group <group_id>`. Each shared plan owed here gets
memberless rows per case and baseline, shared by attachers. Its immutable target
records `deployment.shared_plan = {plan_id, source_revision, group_id}`; the
candidate must contain that source. Cases filter to the target. The first group
pins the plan; edits wait for the next release. Only one group per plan stays
open. Supplemental runs enroll members owing plans there without own cases.
Plans owed only elsewhere let this run succeed while the member waits.
The done gate names the owed target and run; close-out retries when credit arrives.
Cases use the plan's project unless a member owns them.

The driver runs groups outside dispatch; review never stops other groups.
Only the driver receives shared-plan waits and failures, falling back to starter,
then steering. Holders wake for their own QA or close-out. Recipes retain `--env`.

Plan commands have no member: `DEPLOYMENT_MEMBER_REF` refuses as
`qa_plan_member_reference_unsupported`. Read `YOKE_QA_CANDIDATE_TREE` (`root`,
`head_sha`) or detached HEAD. `yoke watch pytest -- <paths>` runs in that candidate.
Post-deploy `command-ci` refuses as `deployment_ci_case_unsupported`; use Command.

`--plan PLAN` at `item-qa` runs the plan's open group for the whole release;
without one it refuses `plan_group_not_open` and lists closed groups.
All cases passing and required stage acceptance close the group.
Its immutable `covered_item_ids` names attachers at closure. Done needs a closed
group for each shared plan, or accepted member-bound cases for a single-member
plan, in its target-qualified completion run (including
supplemental runs that recorded the delivered revision) or superseded lineage.
Later attachers need a new group; verification passes never count post-deploy.

A failed case holds its group open. Retries run only failed cases. The driver
sends back items that owe a fix, or retries, waives or removes them. Abort
notifies unless a retry is live. Changed reports notify again. Closure
withdraws the notice.
Case verdicts settle the active stage or group in the same write. Verdicts
bound to a live execution settle at completion. A failed settlement refuses as
`qa_verdict_settlement_refused` and says whether the verdict persisted. Fix
the cause and record an unsaved verdict again. For a saved verdict, run
`yoke --env CONTROL-PLANE watch deploy -- RUN-ID`.

Correct a wrong group check in its own plan, keeping its case key, then rerun
with the group command below. A single-member correction uses a separate plan:

```text
yoke qa plan run --deployment-run-id RUN --stage item-qa --plan SAME_PLAN --project P
yoke qa plan run --item PREFIX-N --stage STAGE \
    --plan CORRECTED_PLAN --project P --replaces CASE_KEY=FAILED_REQUIREMENT_ID
```

Changed failed group cases get fresh rows; their passes supersede failed history.
Pending and passed cases keep pinned content; new keys wait for another release.
Single-member corrections run only replacement rows; other cases remain owed.

Takeover moves an open group, its results and any running execution to the
successor unchanged; a successor member attaching the plan joins it. Closed
groups stay in the run where they passed. Removing a member or withdrawing its
attachment keeps the group for the members still attaching. When none is left,
`yoke deployment-runs remove-item` retracts the open group and stops its
execution; passed rows are never retracted. A retracted group is never reused:
a later attacher gets a new group.

## Machine partitions

Member plan runs group cases by declared OS or OS slots; an `inherit` chain
stays in its opener's group. Each group runs an immutable roster with its own
lease and the same frozen target. Sessions walk separate plans concurrently,
one live execution per session and target. Begin skips held groups and aborts
abandoned holders. Plan order holds across machine groups.
A host wait or independent review stops the command. Rerun the same scoped
command to reprint a pending review bundle or its recorded passes. Use
`--replaces` to recapture a passed case. Rerunning failed or undetermined
cases starts a fresh execution. Rerun after review to continue remaining
hosts. The member is accepted once every required case passes. Omit
`--test-machine` for groups that need different hosts.

For simultaneous hosts, list at least two OS slots in `method_config.test_machines`
with exactly one `driver` and no singular `os`, e.g.
`[{"os":"linux"},{"os":"macos","driver":true}]`. Map each slot OS to its
`capability_tags`, e.g. `{"macos":["macos:15"]}`, to tag every slot of that OS.
Use `yoke qa plan run`. Each slot takes a distinct free, verified, healthy host.
The set stays leased through review and releases on completion or abort.
[Completed captures remain reviewable](requirement-state.md).
A wait names a host from a blocked OS and gives the lease or verification failure
for each unavailable eligible host of every blocked OS. A failed verification
can queue for repair. A host without a verification result is ineligible.
Queue views show one host per slot and group its alternatives.

An `inherit` chain retains the opener's hosts. Multiple walks in one execution
acquire their combined hosts at one queue place before preparation. Walk one
mission at a time on its recorded driver through walk-end. A retry inside a
chain never reacquires lost custody. If a follower declares different hosts,
`inherited_driver_mismatch` asks you to drop its OS or slots or start a new
chain from a named baseline. Only the opener selects hosts.

An exploratory mission walks after captures and may inherit only at a chain's
tail; no case may inherit after it. Item and deployment scopes isolate the
whole chain so no later capture disturbs its state. Standalone mixed plans
refuse `inherited_mission_requires_isolated_plan`: put the chain in its own
plan or use item/deployment attachment. Declare `inherit` to preserve
preparation.

## Shared host turns and starting state

When a Test Machine is leased or unhealthy, the plan keeps its cursor and
joins the line shared with manual `yoke claims coordination-claim acquire`
waiters. Each execution keeps its own place across retries and recovery.
Adoption clears the old waits and reservations and preserves that place.
Park until the host-turn notice. The runner lists reserved turns first.
A host set reserves only at the front of every line it needs and returns
partial reservations if it falls behind.
A healthy release serves the next eligible waiter. An unhealthy host stays
free for `yoke test-machine verify` or `golden-capture`. A failed SSH connection
records `ssh_unavailable` and queues. Leases power cloud hosts automatically.
Start other hosts or repair SSH, then verify. Ending a session or plan cancels
its waits. Releasing an unused turn aborts a plan whose last wait is gone.

A covering steering seat can move a waiter or pass an unstarted reservation:

```text
yoke test-machine queue place --execution ID --host H --position N --reason TEXT
yoke test-machine queue hand-over --from ID --to ID --host H --reason TEXT
```

Placement survives resume on all the execution's hosts. A position past the
end goes last. Handover leaves the former holder queued and requires the
receiver to be first on its other hosts. A reset or verify keeps its borrowed
turn until it finishes. Retrying an identical result returns its receipt.
A changed result becomes the current receipt.

Removing a release member ends its QA execution and releases its hosts when
every mission already recorded its walk-end restore. Otherwise the removed
mission retains custody for its original owner's walk-end teardown. A deliberate
host release by the holder, a covering steering seat, or claim id cancels the
live execution and releases its entire host set in the same transaction;
it records the release reason and never counts as a QA pass. Stop the runner
and recover the host's starting state before using manual release.

Before it parks, a queued plan runs every remaining host-free automatic case in
its roster — Command and Command (CI) — through the ordinary case runner and
records each result against its requirement. A failing case is recorded and
the plan stays queued; a case whose runner raises stays unrecorded and runs in
order on resume. The park message names the cases it ran. On the host, the
cursor steps over cases already recorded, so resume never reruns them. Machine
cases, `inherit` chains, baselines, and agent- or human-judged cases keep their
roster order.

If a walker discovers a second required host is occupied, return
`WALK_STATUS: HOST_WAIT` and its registered name plus holder evidence. Submit
through the current bundle's `yoke qa plan review-submit ... --stdin`:

```json
{"host_wait":{"test_machine":"linux-example","rationale":"holder evidence"}}
```

Submit this object alone to retain prior capture and queue the immutable target.
It records no verdict or review request. Resume keeps the execution's host
affinity and simultaneous host set. A replacement selects afresh by
`method_config.os` and `capability_tags`. A run's `--test-machine` overrides
recorded affinity. Finish or abort a case that still owns host state before switching.
Record a verdict only after the walk runs.

Exploratory mission `method_config` can declare an apt package fixture:

```json
{
  "executor":"informed_subagent",
  "os":"linux",
  "host_starting_state":{"os_packages":{
    "absent":["python3-venv","python3.12-venv"],"present":[]
  }}
}
```

A Command case whose command calls `yoke test-machine` must declare
`method_config.os` (or OS slots) and `host_baselines` or `inherit`. That makes
it a host Command: it waits in the queue for any matching host and holds that
host's lease while it runs.

Selection reads only the case's OS and tags, even when the requirement has
only the generic <!-- qa:test-machine-capability -->`test-machine` capability.
Authoring refuses a host name on a case with `test_machine_name_forbidden`. To
choose a host for one run of a machine-backed requirement, run
`yoke qa case run --requirement-id N --test-machine NAME`; the choice is never
stored. The host must match the required OS and `method_config.capability_tags`. For example,
require `arch:arm64` on a macOS case that launches an arm64 app and set the
architecture tag on each registered Mac.

Before a plan's first golden reset on each Test Machine, Yoke compares the
harness CLI versions recorded beside that golden with each vendor's latest
release. A golden that is behind is refreshed once under the plan's own host
lease: reset, install the newer CLIs as the test user, capture a new golden,
then begin the case again, so every later reset restores current CLIs. A
failed refresh stops the plan with a `golden_refresh_*` reason and its repair.
Old snapshots left after a verified refresh capture only warn
(`golden_snapshot_retention_failed`, with the host's error and the cleanup).

A declared host baseline restores the golden home. Before new case work, an
unproven mission cleanup also requires a reset: its `reset_owed` machine receipt
names the failed cleanup's baseline, or `fresh-host` when none was declared.
The releasing CLI tries the owed reset once if the host stays free, stopping a
Yoke-started cloud host before and after reset. A waiter that takes the turn
clears the debt in case preparation. The [steering report](../sessions/steering-report-delivery.md#reset-debt)
names any failed reset and its recovery command.
A failed ordinary case restore or current holder's mission restore artifact
also records this debt before custody ends. A terminal case missing its
restore receipt records debt too; an intermediate successful case keeps
its chain state. A cleanup finish always releases its
lease, even without restore proof, and
records restore evidence before committing the release. A deliberate manual
QA_HOST release also records reset debt for every released execution host,
using its case baseline or `fresh-host`, while preserving cancellation and
the recorded release reason. Recovery contracts
require a runner supporting `host-control-reset-recovery-v1`; an older runner
refuses before host work and must be upgraded before retrying.

A named baseline or explicit fixture
undoes only the preceding mission's journal-attributed package delta, applies the declaration and
records proof before walking. Linux and WSL fixtures use apt; a declaration on another OS
refuses with the supported host named. Package changes made through
`yoke qa mission host-command` are journaled, including transitive installs and
failed commands. The owner-only journal lives beside the golden archive,
outside the reset home. No arbitrary package cleanup command is accepted.
Independent host changes outside the journal's changed and declared packages,
including unattended security upgrades, are preserved and become the new base
inventory after restore. Missing attribution refuses before package mutation.
Restoring missing or changed packages requires the recorded versions to remain
available; a failed restore names apt access and journal reconciliation and
blocks execution. Continuations preserve the existing walk and journal.

## Stop host work safely

```text
yoke qa plan abort --execution-id EXECUTION_ID \
    --reason 'Stop this host case'
```

`qa_checkin_busy` pauses setup or cases as `blocked_on_precondition`; keep custody
and resume the same execution after contention clears. Other setup errors fail.
Owners can abort ended runs; settled walks report state. A steering abort returns
`stop_request`; the owner stops at its next case, heartbeat or
[walk-end](exploration-evidence.md). Without a seat,
`qa_execution_stop_requires_steering` refuses.

An in-flight host abort first records cancellation. Until the interrupted
case's cleanup proof is recorded, `qa_abort_restore_pending` retains custody.
Keep the owner connected: heartbeat replies carry cancellation; the runner stops
before its next step, cleans up and submits `starting_state_restore` evidence. A case with a declared
baseline must prove `restored: true` for that baseline.
Other roster cases do not impose their baselines on the interrupted case.
Blocking resets finish before the runner acts on cancellation. Retry abort
only after cleanup proof is recorded; success confirms the lease is released.

Failed cleanup, failed restore or a lost runner retains custody. Stop the old
runner; the lease holder or a project steering seat can reset retained machines
to the interrupted case's baseline:

```text
yoke test-machine reset --test-machine NAME --baseline BASELINE
```

Then retry the same scoped abort command. Only a successful reset receipt for
the same machine and lease, matching that baseline and recorded after the abort
request, proves recovery. Reset retains custody; abort performs normal capture,
review and lease settlement. A stale or failed reset cannot release custody.
Without a declared baseline, recover the runner's no-restore cleanup receipt.
Preserve the execution, capture and restore diagnostics. A liveness heartbeat
does not mark the next case in flight. Host-case admission identifies its
cursor; only a subsequent check-in for that admitted cursor marks host work
in flight. Admission alone does not require restoration. After the last case,
heartbeats record no check-in. Both walking and review re-enter the bundle,
never a paused case.

After an abort, rerun the same scoped command. The fresh execution leaves out
each case whose newest run passed with its evidence on this same target,
including passes the aborted execution recorded, and starts at the first case
still owed; a multi-host member moves on to the next host. A passed case
stays while a later case of its chain is still owed, so the chain runs again
from its opener. A case whose review lands after the roster froze is recorded
`retained` when it and every later case of its chain now pass, instead of
running or blocking its followers. A pass on
another target still requires a fresh run. Cases a stopped execution's pending
review holds stay out. With nothing owed the run refuses `qa_plan_nothing_owed`,
listing the stage's blockers and next commands; once every case passed, stage
acceptance settles on the newest stopped execution. A live execution keeps its
own roster: abort it first to drop cases passed elsewhere.

Recover communication through [exact execution recovery](deployment-qa-continuity.md#recover-communication-on-the-frozen-execution), preserving saved receipts and host state.

## Related

- [Verification](index.md)
- [QA platform](platform.md)
