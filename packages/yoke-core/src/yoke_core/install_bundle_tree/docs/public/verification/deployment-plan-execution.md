# Deployment plan execution

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > [Verification](index.md) > Deployment plan execution
<!-- /yoke:breadcrumbs -->

Use the attaching member's pinned stage to run or resume its owed cases:

```text
yoke qa plan run --deployment-run-id RUN --stage STAGE --member PREFIX-N --project P
```

Read `yoke qa plan run --help` for correction and continuation options.
[Case attachment](case-attachment.md#binding-a-deployment-case-to-its-stage-and-member)
owns the scope and target-binding contract.

Only requirements with an executable method are copied from admission.
Method-less standing requirements remain on their source item; a selected
plan supplies the executable stage cases. A deployment-stage target (persistent environment or run preview) supplies
`target_env` even when a correction case has no `target_envs` selector, so its
scope matches the case it replaces.

## Shared plan credit

Members attaching the same post-deploy plan share its case rows and ordered
execution when the plan id, source revision and observed execution target match.
A plan counts as attached when the member selects it at the stage: a live or
admission-frozen attachment, or an admitted requirement that plan owns.
A plan only one run member attaches stays that member's private copy and keeps
its `deployment_member_item_id`; a formed group stays shared until its last
attaching member leaves.
The shared execution records the member that requested it, separately from its
run-wide subject. Continuation and host-wait commands retain that member as
`--member`; another attaching member resuming it does not change the requester.
The shared target omits `deployment.member_item_id` and records
`deployment.shared_plan`; the run and stage remain explicit. Each member waits
only for its attached groups. A failing shared case blocks every attaching
member; a different plan, source revision or target stays separate. Flow-pinned
plans and directly authored member cases retain their declared scope.

Recording a case verdict while its stage is executing settles that stage in
the same write: a shared case settles its group and credits every attaching
member. When the stage cannot settle, the write refuses as
`qa_verdict_settlement_refused` with the cause and whether the verdict
persisted. Record an unpersisted verdict again after repairing the cause; for a
persisted one, re-drive the run with `yoke watch deploy -- RUN` so its runner
adopts it.

Use the `--stage` / `--member` command above. It runs unfinished private
member cases first, retaining their own target, order, host prerequisites and
reviews. Completing that private roster ends this invocation; it does not
start an attached shared campaign. Private evidence alone does not accept a
member that still owes shared evidence. Once private acceptance is complete,
the same command selects the next unfinished shared group and reuses
completed group evidence. A shared execution owned by another session, or a
different group using the stage's cursor, returns `state=waiting` with
`shared_execution_wait.execution_id` and `owner_session_id`. Keep the work claim
and park with `yoke sessions touch --mode parked --reason "waiting for shared QA"`.
The deployment's member stage
line retains the wait. Passing shared evidence credits every attaching member;
completion, abort or error wakes members still owing QA to retry their own
stage/member command. The owner resumes its existing execution as usual.
Refresh and declared corrections
also use an attaching member and keep the failed group's target identity.
For a correction, name its plan and failed requirement:

```text
yoke qa plan run --deployment-run-id RUN --stage STAGE --member PREFIX-N \
    --plan CORRECTED_PLAN --project P --replaces CASE_KEY=FAILED_REQUIREMENT_ID
```

This walk selects only the correction plan's rows, including inside a shared
group. Other original cases and unrelated groups remain owed independently.
Replacement scopes stay in the frozen selection, so later materialization
does not create private copies of shared corrections. A passing independent
verdict supersedes the failed requirement.
A member refresh with `--plan` naming the member's own plan refreshes only that
member's rows, so a live run-wide walk of a shared plan does not block it.
Removing one member or withdrawing its attachment preserves shared evidence for
the members still attached. Removing the last attaching member with
`yoke deployment-runs remove-item` retracts the group's unsettled rows, so an
orphaned group never stays a run-wide blocker. Source-case refresh and withdrawal resolve the same
shared target; a recorded run keeps the existing retraction refusal.
At materialization, redundant member copies retire as history. A live cursor
using those copies refuses as `shared_plan_duplicate_execution_live`: its owner
must finish or abort it before retrying; conversion makes no partial changes.

## Machine partitions

For a deployment member whose cases require several Test Machines, the scoped
command automatically executes one immutable roster per machine. Each roster
holds its own lease and participates in that host's FIFO. It keeps the same
run, stage and frozen private-member or shared-plan target.
A waiting host or independent review stops the command. Re-enter the same
scoped command while review is pending to reprint that bundle without
recapturing. Once a verdict batch is recorded, the same command reprints
passing verdicts and does not capture those settled requirements; a new
capture of a passed requirement uses --replaces. A failed or undetermined
verdict stays open: rerunning begins a fresh execution that captures it
again. After review settles, rerun to continue any remaining hosts.
Completed scoped cases with passing evidence are retained. The member is
accepted only when every required case passes. Omit --machine for this
multi-machine form: a single host pin cannot satisfy conflicting constraints.

For one case that needs several hosts simultaneously, declare its driving host
as `method_config.machine` and every required host in `method_config.machines`:
`{"machine":"macos-example","machines":["linux-example","macos-example"]}`. Names must be
registered, unique, and include the driving host. Run this case through
`yoke qa plan run`; direct case execution refuses it. The
runner acquires every host through its FIFO in sorted name order, releases
partial acquisitions on contention, and retains the full set through case
execution and mission review. Completion or abort releases the set; [completed captures remain reviewable](requirement-state.md). Cases
with different driving hosts or declared sets use separate execution rosters.

## Shared host turns and starting state

An occupied or unhealthy Test Machine is a wait, never a FAIL. If your host
is busy, let the plan runner queue you, then park; you are woken when it is
your turn. Start or resume the plan as usual: when a host its case needs is
leased, or its newest health fact is a failed verification, plan acquisition
keeps its cursor open and its session joins the host's waiting line
(`qa_host_waits`), the same FIFO line a refused manual
`yoke claims coordination-claim acquire --key QA_HOST:<machine>` joins. The
runner prints `Queued for QA host <machine>, position N of M` with the park
command; write no host hold of your own. A session keeps its place from its
first wait and across retries. Every release of the host — including
`yoke claims work release --claim-id N` — reserves it for the oldest live
waiter and sends that session the exact resume command; stopped owners use the
same harness-neutral wake route as other control-plane notices. An unhealthy
host is never reserved: it stays free for the operator's
`yoke test-machine verify` or `yoke test-machine golden-capture`, and that
operation's successful release wakes the first waiter. A plan case whose host
SSH cannot reach (`ssh_unavailable`: connect timeout, refusal, no route or a
rejected key) records that failed verification itself and queues the same way
instead of recording an error verdict. Yoke never starts a stopped host: start
it (or repair its SSH), then run `yoke test-machine verify`. Reset and diagnosis
receipts do not change health. Ending the session, settling the execution, or
releasing an unused reservation cancels the wait and passes a reserved turn to
the next waiter.

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
{"host_wait":{"machine":"linux-example","rationale":"lease holder and resume point"}}
```

Submit this object alone. It records no verdict or human review request,
retains the old capture and bundle as history, and queues a new capture against
the identical immutable target. Host-ready and continuation commands omit
`--machine`, so every platform in a multi-host roster can resume. The scheduler
keeps simultaneous cases on their declared driver with the full host set. For
single-host cases it returns each previously used platform to its recorded host; only a new platform
selects a fresh eligible host. Correction-ready commands also omit the pin; scheduling retains each corrected
case’s failed attempt host through its requirement replacement history.
Use a verdict only after the required host was available and the walk ran.

Exploratory mission `method_config` can declare an apt package fixture:

```json
{
  "executor":"informed_subagent",
  "machine":"linux-example",
  "host_starting_state":{"os_packages":{
    "absent":["python3-venv","python3.12-venv"],"present":[]
  }}
}
```

A Command case whose command calls `yoke test-machine` must declare
`method_config.machine`; without it the case would run outside the host's queue
and meet `test_machine_leased`, so authoring refuses it naming that field.

`method_config.machine` selects that registered host even when this direct
requirement has only the generic <!-- qa:test-machine-capability -->`test-machine` capability. Admitted deployment
copies retain the pin; omitting `--machine` does not permit another host, and a
conflicting run pin is refused before a lease is acquired.

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
yoke qa plan abort --deployment-run-id RUN --execution-id EXECUTION_ID \
    --reason 'Stop this host case'
```

The execution owner can abort after its deployment run ends; the abort records
the terminal run status in its release reason. An already-settled execution
reports its recorded state. A failed run does not require returning to an
active stage to settle an execution.

An in-flight host abort first records cancellation. Until the interrupted
case's cleanup proof is recorded, it refuses with `qa_abort_restore_pending`
and retains host custody. Keep the owning runner connected: heartbeat replies
carry cancellation, the runner stops before its next step, finishes fixture
cleanup and submits `starting_state_restore` evidence. A case with a declared
baseline must prove `restored: true` for that baseline. An `as_is` case or a
chain without a declared baseline records that there is no starting state to
restore; that cleanup receipt permits release with `restored: false`.
Other roster cases do not impose their baselines on the interrupted case.
Blocking resets finish before the runner acts on cancellation. Retry abort
only after cleanup proof is recorded; success confirms the lease is released.

If cleanup or a required restore fails, or the runner is gone, custody stays
held. Stop the old runner before recovery. The lease-holding session or a live
steering seat covering the project can reset each retained machine to the
interrupted case's declared baseline:

```text
yoke test-machine reset --project P --machine NAME --baseline BASELINE
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
the cursor names no case, so a heartbeat records no check-in; an execution in
`awaiting_agent_review` re-enters to its review bundle, never as a paused case.

After an abort, rerun the same scoped command. The fresh execution leaves out
each case whose newest run passed with its evidence on this same target,
including passes the aborted execution recorded, and starts at the first case
still owed; a multi-host member moves on to the next host. A passed case
stays while a later case of its chain is still owed, so the chain runs again
from its opener. A case whose review lands after the roster froze is recorded
`retained` when it and every later case of its chain now pass, instead of
running or blocking its followers. A pass on
another target, such as a new release lineage, still requires a fresh run. When
every case already passed, the whole roster runs again, because stage
acceptance needs one completed scoped execution. A live execution keeps its
own roster: abort it first to drop cases passed elsewhere.

## Recover communication on the frozen execution

```text
yoke qa plan run --deployment-run-id RUN --stage STAGE --member PREFIX-N \
    --project P --resume-execution-id EXECUTION_ID
```

Keep the original scope and source arguments; omit `--member` for a run-scoped
stage. This re-enters the exact live cursor with frozen candidate and custody
validation, without rematerializing cases or allocating another campaign.
A lost reply is an unknown outcome, not permission to abort or replay an action.
Follow the [check-in recovery contract](standalone-plans.md#recover-a-lost-check-in-response)
for pause receipts, saved recording evidence and refusal recovery.

## Related

- [Verification](index.md)
- [QA platform](platform.md)
