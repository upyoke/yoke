"""Help text for ``yoke qa plan run``: the subject/scope matrix it teaches."""

#: The subject/scope matrix: which invocation credits which subject, and the
#: release-time form whose omission leaves a stage unsatisfied. Read as
#: ``yoke qa plan run --help``.
QA_PLAN_RUN_EPILOG = """\
Pick the subject, then the scope
--------------------------------
Select an item, deployment run, or manual project plan.

  yoke qa plan run --plan PLAN --project P
      Run a project plan now, recording standalone evidence without changing
      any item or deployment gate. Command cases require --checkout-path and
      --expected-sha (full SHA); command-ci also requires --expected-branch
      naming a published branch or tag at that commit. Its named workflow
      dispatches with the case's declared inputs; no lane is pushed.
      Abort with `yoke qa plan abort --project P --execution-id ID --reason TEXT`;
      Use --resume-execution-id ID --continue-mission for a stale-settled walk.

  --item PREFIX-N --transition TRANSITION
      An item's own attached plans, for a lifecycle transition's QA gate.
      Requires --transition; does not accept --plan, because an item uses the
      plans already attached to it. For multiple active lanes, hold the matching
      item/task claim and select its exact registered --checkout-path PATH
      --expected-branch BRANCH --expected-sha FULL_SHA. Cases whose newest
      run passed at the lane's recorded head are skipped; the rest run one
      execution target at a time, each after the previous one passed.

  --item PREFIX-N --stage STAGE [--plan PLAN] --project PROJECT
      Fresh item QA uses its current completion authority, including a carrier
      release from another project. A selected plan names its target environment.
      Missing or unready delivery authority refuses with its recovery.

  --deployment-run-id RUN --stage STAGE [--plan PLAN] --project PROJECT
      Initial run-level orchestration only. The stage must be the run's active
      pinned QA stage. Item QA uses --item instead.

Passed cases and stopped executions awaiting review are retained. With nothing
owed, qa_plan_nothing_owed lists the remaining blockers and recovery commands.
Existing executions resume by --resume-execution-id ID; their current owner is
resolved from stored authority, without selecting a release or member.

Release-time scope: a stage credits only its own name
-----------------------------------------------------
A deployment QA stage is satisfied only by requirements bound to that stage's
own name. An item-scoped stage reads private member cases and attached shared
plan/source/target groups; each member waits only on its attached groups.
Matching attachments share case rows and an ordered execution, with member
identity omitted from the shared target. A pass credits every attaching member;
a shared failure blocks them all. Different plans, sources and targets stay
separate. The member command runs unfinished private cases first with their own
target, ordering, host prerequisites and reviews. Completing that private roster
ends this invocation without starting a shared campaign; shared acceptance is
still required. Once private acceptance is complete, the same command reuses
completed group evidence and continues its next unfinished shared group.
Each session walks its own group; when other sessions' walks hold every group
you owe, it returns state=waiting with shared_execution_wait.execution_id and
owner_session_id.
Keep the claim and park with
yoke sessions touch --mode parked --reason "waiting for shared QA". Passing shared
evidence credits attaching members; settlement wakes members still owing QA
to retry their own item/stage command. The owner resumes its walk as usual.

Use --item PREFIX-N --stage STAGE for item QA. Run-level orchestration retains
its run/stage context. An exact --requirement-id selects the stored case binding;
an agent_mission starts a one-requirement execution with its retained lease,
review bundle and main-agent verdict. An inherit mission needs its ordered
predecessor and must use the plan command.

When the stage names no concrete cases, --plan records the executor's
project-owned selection -- and only then. A stage already naming its own cases
(pinned, frozen, member-attached, admitted, or directly authored) refuses
--plan unless --replaces or --replaces-requirement names every corrected case. This
atomic correction binds each case to the same run, stage, member and target;
it does not add an unrelated second set of obligations.
Materialization stamps the member project's deployed target for member QA,
or the run project's target for run QA,
onto the cases. Takeover preserves that start-time context, case evidence and
custody while changing the owning release. Inherited QA can observe multiple
builds at the same authorized environment; Browser evidence records the served
revision. Command cases retain their admitted source checkout. Each command
runs in a disposable checkout the runner removes afterwards, however
far the default branch has moved. --checkout-path overrides that tree and is
refused unless it sits at the candidate; --allow-tree-mismatch declares the
case reads nothing from the checkout.

For a deployment member whose cases require several Test Machines, the scoped
command automatically executes one immutable roster per machine. Each roster
holds its own lease and participates in that host's FIFO. It keeps the same
run, stage and frozen private-member or shared-plan target.
A waiting host or independent review stops the command. Re-enter the same
scoped command while review is pending to reprint that bundle without
recapturing. Once a verdict batch is recorded, the same command reprints
those verdicts and does not capture the settled requirements; a new capture
uses --replaces. After review settles, rerun to continue any remaining hosts.
Completed scoped cases with passing evidence are retained. The member is
accepted only when every required case passes. Omit --machine for this
multi-machine form: a single host pin cannot satisfy conflicting constraints.

Recover an unknown response on the same execution
------------------------------------------------
  yoke qa plan run --resume-execution-id EXECUTION_ID

The execution supplies its subject, stage and target. Supplied item, source and
machine hints must agree with its stored authority. A lost reply is an unknown outcome,
not a failed action. Only a check-in retries briefly with the same request id;
it uses the durable request ledger to recover a late success. Other operations
never replay automatically. outcome_unknown exits with the waiting status and
names the execution, phase, request, attempts and saved evidence.
A confirmed pause retains the cursor, results and machine custody without
renewing leases. An unconfirmed pause retains the last known state; keep its
owner parked. For an unconfirmed pre-case pause, add the returned
--recovery-file PATH to reapply that receipt once connectivity returns.
A consumed receipt or changed cursor refuses. Re-entry revalidates the frozen target, actor/session and live
custody. A case that has not durably advanced refuses automatic re-entry. Preserve its
saved result and request evidence and ask the control-plane operator to inspect
the durable cursor; no command replays an unrecorded case submission. A lost
heartbeat during cleanup is captured and does not block result submission;
if submission also loses its response, its payload is saved as outcome_unknown. Do not reset hosts, replay one-shot actions,
create a new campaign or revive terminal history to recover communication.
For a walk explicitly settled by the stale sweep, use --resume-execution-id ID
--continue-mission. This preserves the old history and host state, and refuses
if another eligible walk has replaced the named source.
Pause/resume requires a serving release carrying those registered functions;
a version-skew refusal names that floor and the control-plane operator.

Who runs it, and what follows
-----------------------------
The item owner parked at its release wait runs its own stage when the
deployment wake asks for it (an operator-woken desktop owner is re-entered by
its operator or a steering seat instead), then checks whether the item reached
done. A delivery wake names `yoke merge item PREFIX-N --result ...
--verification ...` only for a close-out delivery could not finish. The steering seat drives the run and never
substitutes a run-wide pass for a member's stage. See `yoke merge item --help`
for the close-out and `yoke deployment-runs --help` for the run itself.

Replacing a failed case with a corrected one
--------------------------------------------
When an admitted case failed because its capture or probe was wrong, create a
plan containing only its corrected case and name the failed requirement:

  yoke qa plan run --item PREFIX-N --stage STAGE \\
      --plan CORRECTED_PLAN --project P --replaces CASE_KEY=FAILED_REQUIREMENT_ID

The selected --plan limits this invocation to that plan's correction rows,
including within a shared group; original and unrelated cases do not replay.
Replacement scopes stay frozen, so later materialization creates no private
copy of a shared correction. The failed attempt remains history. The new
blocking case keeps the stage waiting until its independent verdict passes;
that pass supersedes the old row and resumes the run driver. A missing sibling
case still blocks. Retries reuse the declaration. To correct a failed
correction, name its requirement id. For an item subject, pass --replaces to
`yoke qa plan materialize --item PREFIX-N --transition T` before this run.
If a case key expands across host baselines, use --replaces-requirement FAILED_ID
instead. Keep the same case key in the corrected plan; only the named row's
baseline is materialized and linked, while sibling baselines remain unchanged.
If the corrected direct requirement already exists, declare it with `yoke qa
requirement supersede --requirement-id FAILED_ID
--superseded-by-requirement-id CORRECTED_ID --rationale 'corrected case'
--declare-replacement`, then run the scoped plan without --plan. The old case
leaves its roster immediately; the corrected case still needs a pass.

Stopping a host case
-------------------
  yoke qa plan abort --execution-id ID --reason TEXT

--reason holds at most 200 characters: a code and a short diagnosis. Put the
full rationale in the Progress Log or an artifact and cite it.

Another session's live execution stops only from a live steering seat. The
abort then records a stop request (receipt stop_request) and the owning runner
stops at its next case check-in or host heartbeat, cleans up and settles it.

An in-flight host abort records cancellation and returns qa_abort_restore_pending
while custody remains held. Keep the runner connected: it stops between steps,
finishes cleanup, restores the declared starting baseline and records proof.
Retry abort after cleanup; success means restoration is confirmed and the lease
released. Failed restore retains custody: stop the runner, then the lease holder
or a covering steering seat runs yoke test-machine reset --project P --machine
NAME --baseline BASELINE using the interrupted case's declared baseline. Retry
abort after this successful reset; older or failed receipts cannot settle it.
A case without a baseline still needs its runner's no-restore cleanup receipt.
A blocking reset finishes before cancellation is acted on.

Failed member QA recovery
-------------------------
The one-line notice names RUN, STAGE, ITEM and each failed requirement ID.
No notice is sent back to the session whose execution produced that verdict;
it already holds the result. A holder or steering recipient should read:

  yoke deployment-runs get RUN
  yoke qa requirement get --requirement-id FAILED_REQUIREMENT_ID
  yoke qa run list --requirement-id FAILED_REQUIREMENT_ID

Determine whether the environment, case, or member code caused the failure.
Claim or staff ITEM before changing it if its holder is gone.
For an environment failure, leave the item in release and run fresh QA on the
current authorized environment:

  yoke watch qa-plan -- --item ITEM --stage STAGE \\
      --project PROJECT

For a defective case, use the correction-only plan and --replaces recipe
above (through yoke watch qa-plan --), or declare the corrected direct
requirement before running the scoped plan without --plan.
For a member code defect, refresh any survey required by its pinned workflow,
then take the ordinary backward transition, without operator approval:

  yoke lifecycle transition ITEM --from release --to implementing \\
      --reason 'Post-deploy QA found a member code defect'

Keep the claim and worktree; correct, verify and merge the item. Have the run
driver settle the old run without changing its pin. The failed run and QA
remain history; a new run must deploy the corrected commit.
"""


__all__ = ["QA_PLAN_RUN_EPILOG"]
