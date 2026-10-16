# Deployment plan execution

Use the attaching member's pinned stage to run or resume its owed cases:

```text
yoke qa plan run --deployment-run-id RUN --stage STAGE --member PREFIX-N --project P
```

Read `yoke qa plan run --help` for correction and continuation options.
[Case attachment](case-attachment.md#binding-a-deployment-case-to-its-stage-and-member)
owns the scope and target-binding contract.

## Shared plan credit

Members attaching the same post-deploy plan share its case rows and ordered
execution when the plan id, source revision and observed execution target match.
A plan counts as attached when the member selects it at the stage: a live or
admission-frozen attachment, or an admitted requirement that plan owns.
A plan only one run member attaches stays that member's private copy and keeps
its `deployment_member_item_id`; a formed group stays shared until its last
attaching member leaves.
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
completed group evidence. Another
session's live execution remains owned by that session; continue its watcher
and retry afterward. `shared_plan_execution_busy` names a different group
already using the stage's ordered cursor. Refresh and declared corrections
also use an attaching member and keep the failed group's target identity.
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
A waiting host or independent review stops the command; after the wait or
review settles, rerun the same scoped command to continue the remaining hosts.
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
execution and mission review. Completion or abort releases the set; [completed captures remain reviewable](requirement-state-model.md). Cases
with different driving hosts or declared sets use separate execution rosters.

## Shared host turns and starting state

An occupied Test Machine is a wait, never a FAIL. Plan acquisition keeps its
cursor open and its session joins the host's waiting line (`qa_host_waits`),
the same FIFO line a refused manual
`yoke claims coordination-claim acquire --key QA_HOST:<machine>` joins. A
session keeps its place from its first wait and across retries. Every release
of the host — including `yoke claims work release --claim-id N` — reserves it
for the oldest live waiter and sends that session the exact resume command;
stopped owners use the same harness-neutral wake route as other control-plane
notices. Ending the session, settling the execution, or releasing an unused
reservation cancels the wait and passes a reserved turn to the next waiter.

If a walker discovers a second required host is occupied, return
`WALK_STATUS: HOST_WAIT` and its registered name plus holder evidence. Submit
through the current bundle's `yoke qa plan review-submit ... --stdin`:

```json
{"host_wait":{"machine":"linux-example","rationale":"lease holder and resume point"}}
```

Submit this object alone. It records no verdict or human review request,
retains the old capture and bundle as history, and queues a new capture against
the identical immutable target. The same scoped plan-run command resumes it.
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

`method_config.machine` selects that registered host even when this direct
requirement has only the generic <!-- qa:test-machine-capability -->`test-machine` capability. Admitted deployment
copies retain the pin; omitting `--machine` does not permit another host, and a
conflicting run pin is refused before a lease is acquired.

Only an explicitly declared host baseline restores the golden home. A mission
declared `as_is` keeps the home it finds and, absent `host_starting_state`, leaves
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
