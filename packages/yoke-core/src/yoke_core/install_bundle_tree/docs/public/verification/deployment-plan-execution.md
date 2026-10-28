# Deployment plan execution

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Verification](index.md) > Deployment plan execution
<!-- /yoke:breadcrumbs -->

Run item cases (QA written on one item, or added by the flow without a plan)
with the item and its pinned stage:

```text
yoke qa plan run --item PREFIX-N --stage STAGE --project P
```

A post-deploy plan attached to release members runs once per release as one
[plan group](#plan-groups):

```text
yoke qa plan run --deployment-run-id RUN --stage item-qa --plan PLAN --project P
```

Failure: [item recovery](failed-item-qa.md). Options: `yoke qa plan run --help`.
Scope and target binding: [Case attachment](case-attachment.md#binding-a-deployment-case-to-its-stage-and-member).

Admission copies executable item cases; others stay on the source item.
Attaching a post-deploy plan writes no item copy, and admission saves no plan.
The plan supplies cases; stage targets supply `target_env`, preserving scope
for corrections without `target_envs`.

[QA continuity](deployment-qa-continuity.md): item authority, release takeover,
cross-build observations and exact-execution recovery.

## Plan groups

When `item-qa` dispatches, each attached plan (a live attachment or project
default, unretired, for the run's environment) that a member still owes gets
one plan group: memberless run rows, one per case and required baseline, at any
number of attaching items. Its target records
`deployment.shared_plan = {plan_id, source_revision, group_id}`; `group_id` is
set once and never changes. The deployed candidate must contain the plan's
source revision, and cases are filtered to the target. The run pins each plan
at its first group, so plan edits during a release wait for the next release.
A run holds at most one open group per plan.

Dispatch launches nothing and wakes no item holder for a plan group. One
run-scoped notice lists each pending group with its items and run command, sent
to the live run driver, else the live session that started the run, else
steering. Only a new pending group re-sends it. Holders of plan-only items
park; the stage and the next stage wait while any group is open.

`--plan PLAN` at `item-qa` runs that plan's open group for the whole release;
no command selects one member's plan cases, so attach the plan instead. With no
open group it refuses `plan_group_not_open`, listing the plan's closed groups.

A group closes when the existing settlement rules accept it: every case passes
(a corrected case counts through its replacement) and any required stage
acceptance is recorded. Closing records `covered_item_ids` once: the run
members attaching the plan at that moment. A closed group never changes or
moves. An item is done only when each attached post-deploy plan has a closed
group covering it, in its target-qualified completion run (including a
supplemental staging run that recorded the delivered revision) or a run that
run superseded. An item or attachment that arrives after a group closed is not
covered: it gets a new group with its own `group_id`. A verification pass never
counts for post-deploy.

A failing case keeps the group open; a retry reruns only failed cases. One
notice to the same recipient names the report and the group's items and
releases no member; that session decides who fixes what.

Recording a case verdict while its stage is executing settles that stage in
the same write; a group case settles its group. When the stage cannot settle,
the write refuses as `qa_verdict_settlement_refused` with the cause and whether
the verdict persisted. Record an unpersisted verdict again after repairing the
cause; for a persisted one, re-drive the run with `yoke watch deploy -- RUN` so
its runner adopts it.

For a correction, name its plan and failed requirement. A group case uses the
group form above with the same flag:

```text
yoke qa plan run --item PREFIX-N --stage STAGE \
    --plan CORRECTED_PLAN --project P --replaces CASE_KEY=FAILED_REQUIREMENT_ID
```

Only the correction plan's rows run; other cases remain owed. A passing
independent verdict supersedes the failed requirement.

Takeover moves an open group, its results and any running execution to the
successor unchanged; a successor member attaching the plan joins it. Closed
groups stay in the run where they passed. Removing a member or withdrawing its
attachment keeps the group for the members still attaching. When none is left,
`yoke deployment-runs remove-item` retracts the open group and stops its
execution; passed rows are never retracted. A retracted group is never reused:
a later attacher gets a new group.

## Machine partitions

When a deployment member's cases require several Test Machines, the scoped
command executes one immutable roster per machine group, each with its own
lease in that host's FIFO and the same run, stage and frozen target. Sessions
walk separate plans concurrently, one live execution each. Begin skips held
groups and aborts abandoned holders. Plan order holds across machine groups.
A waiting host or independent review stops the command. Re-enter the same
scoped command while review is pending to reprint that bundle without
recapturing. Once a verdict batch is recorded, the same command reprints
passing verdicts and does not capture those settled requirements; a new
capture of a passed requirement uses --replaces. A failed or undetermined
verdict stays open: rerunning begins a fresh execution that captures it
again. After review settles, rerun to continue any remaining hosts.
Completed scoped cases with passing evidence are retained. The member is
accepted only when every required case passes. Omit --test-machine for this
multi-machine form: a single host pin cannot satisfy conflicting constraints.

For one case that needs several hosts simultaneously, declare its driving host
as `method_config.test_machine` and every required host in
`method_config.test_machines`; names must be registered, unique, and include
the driving host. Run this case through `yoke qa plan run`; direct case
execution refuses it. The
runner acquires every host through its FIFO in sorted name order, releases
partial acquisitions on contention, and retains the full set through case
execution and mission review. Completion or abort releases the set; [completed captures remain reviewable](requirement-state.md). Independent cases with different driving hosts or declared sets use separate
execution rosters. An `inherit` chain uses its head driver and the union of
its hosts as one execution group. Admission reserves all chains' hosts for
that driver before the first capture and retains them through completion,
review or abort. Contention releases partial acquisitions and queues the
chain; a retry never reacquires lost custody. Definition-time validation
refuses `inherited_driver_mismatch` for a changed driver: use the predecessor's
`method_config.test_machine`, or start a new baseline / `as_is` chain.

An exploratory mission walks after captures and may inherit only at a chain's
tail; no case may inherit after it. Item and deployment scopes isolate the
whole chain so no later capture disturbs its state. Standalone mixed plans
refuse `inherited_mission_requires_isolated_plan`: put the chain in its own
plan or use item/deployment attachment. Declare `inherit` to preserve
preparation; `as_is` opens a separate chain.

## Shared host turns and starting state

An occupied or unhealthy Test Machine is a wait, never a FAIL. If your host
is busy, let the plan runner queue you, then park; you are woken when it is
your turn. When a host its case needs is leased, or its newest health fact
is a failed verification, plan acquisition keeps its cursor open and its
session joins the host's waiting line (`qa_test_machine_waits`), the same
FIFO line a refused manual `yoke claims coordination-claim acquire --key QA_HOST:<machine>`
joins. The runner prints `Queued for QA host <machine>, position N of M` with
the park command; write no host hold of your own. A session keeps its place
from its first wait and across retries; a rerun of an aborted walk
that held the host takes its place. Every release of the host — including
`yoke claims work release --claim-id N` — reserves it for the oldest live
waiter and sends that session the exact resume command; stopped owners use the
same harness-neutral wake route as other control-plane notices. An unhealthy
host is never reserved: it stays free for the operator's
`yoke test-machine verify` or `yoke test-machine golden-capture`, and that
operation's successful release wakes the first waiter. A plan case whose host
SSH cannot reach (`ssh_unavailable`: connect timeout, refusal, no route or a
rejected key) records that failed verification itself and queues the same way
instead of recording an error verdict. Leases start and stop cloud hosts;
start others (or repair SSH), then run `yoke test-machine verify`. Reset and
diagnosis receipts do not change health. Ending the session, settling the
execution, or releasing an unused reservation cancels the wait and passes a
reserved turn to the next waiter.

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

Submit this object alone. It records no verdict or human review request,
retains the old capture and bundle as history, and queues a new capture against
the identical immutable target. Host-ready and continuation commands omit
`--test-machine`, so every platform in a multi-host roster can resume. The scheduler
keeps simultaneous cases on their declared driver with the full host set. For
single-host cases it returns each previously used platform to its recorded host; only a new platform
selects a fresh eligible host. Correction-ready commands also omit the pin; scheduling retains each corrected
case’s failed attempt host through its requirement replacement history.
Use a verdict only after the required host was available and the walk ran.

Exploratory mission `method_config` can declare an apt package fixture:

```json
{
  "executor":"informed_subagent",
  "test_machine":"linux-example",
  "host_starting_state":{"os_packages":{
    "absent":["python3-venv","python3.12-venv"],"present":[]
  }}
}
```

A Command case whose command calls `yoke test-machine` must declare
`method_config.test_machine`; without it the case would run outside the host's
queue and meet `test_machine_leased`, so authoring refuses it naming that field.

`method_config.test_machine` selects that registered host even when this direct
requirement has only the generic <!-- qa:test-machine-capability -->`test-machine` capability. Deployment
requirements retain the pin; omitting `--test-machine` does not permit another
host, and a conflicting run pin is refused before a lease is acquired.

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
The next holder resets first, including an agent mission, `as_is` case or
case without a baseline. Failed recovery records `machine_needs_repair` and
the exact `yoke test-machine reset` command; the steering report shows that
machine and command until a later successful reset receipt clears the debt.
A failed ordinary case restore or current holder's mission restore artifact
also records this debt before custody ends. A terminal case missing its
restore receipt records debt too; an intermediate successful case keeps
its chain state, and an intentional `as_is` no-restore receipt remains proof
that its declared cleanup finished. A cleanup finish always releases its
lease, even without restore proof, and
records restore evidence before committing the release. A deliberate manual
QA_HOST release also records reset debt for every released execution host,
using its case baseline or `fresh-host`, while preserving cancellation and
the recorded release reason. Recovery contracts
require a runner supporting `host-control-reset-recovery-v1`; an older runner
refuses before host work and must be upgraded before retrying.

A mission declared `as_is` otherwise keeps the home it finds and, absent
`host_starting_state`, leaves
packages and their journal untouched. A named baseline or explicit fixture
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
baseline must prove `restored: true` for that baseline. An `as_is` case or a
chain without a declared baseline records that there is no starting state to
restore; that cleanup receipt permits release with `restored: false`.
Other roster cases do not impose their baselines on the interrupted case.
Blocking resets finish before the runner acts on cancellation. Retry abort
only after cleanup proof is recorded; success confirms the lease is released.

Failed cleanup, failed restore or a lost runner retains custody. Stop the old
runner; the lease holder or a project steering seat can reset retained machines
to the interrupted case's baseline:

```text
yoke test-machine reset --project P --test-machine NAME --baseline BASELINE
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

## Recover communication on the frozen execution

Use the [exact execution recovery](deployment-qa-continuity.md#recover-communication-on-the-frozen-execution)
recipe; preserve its saved receipts and host state.

## Related

- [Verification](index.md)
- [QA platform](platform.md)
