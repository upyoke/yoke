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
      --continue-mission resumes a
      walk settled by the stale sweep while preserving its host state.

  --item PREFIX-N --transition TRANSITION
      An item's own attached plans, for a lifecycle transition's QA gate.
      Requires --transition; does not accept --plan, because an item uses the
      plans already attached to it.

  --deployment-run-id RUN --stage STAGE [--member PREFIX-N] [--plan PLAN]
      --project PROJECT
      One frozen QA stage of a deployment run. The stage must be the run's
      active pinned QA stage.
      PROJECT is the member's project for item QA, or the run's for run QA.

Release-time scope: a stage credits only its own name
-----------------------------------------------------
A deployment QA stage is satisfied only by requirements bound to that stage's
own name -- and an item-scoped stage by requirements bound to the member too.
So the scope flags are not optional decoration:

  * Run-scoped stage  -> --stage STAGE, no --member.
  * Item-scoped stage -> --stage STAGE --member PREFIX-N. The run-wide form is
    refused here rather than recording a pass the stage would ignore.

Dropping --stage or --member is the failure that looks like success: cases run,
verdicts record, and the stage still reads unsatisfied because nothing credited
it. `yoke qa case run --requirement-id N` refuses an item-scoped binding
and names this command instead of exiting zero with an uncredited pass.

When the stage names no concrete cases, --plan records the executor's
project-owned selection -- and only then. A stage already naming its own cases
(pinned, frozen, member-attached, admitted, or directly authored) refuses
--plan unless --replaces names every case in a correction-only plan. This
atomic correction binds each case to the same run, stage, member and target;
it does not add an unrelated second set of obligations.
Materialization stamps the run's own deployed target
onto the cases, so a plan authored before this release still verifies it. A
deployment case is bound to the candidate the run deployed, not to your lane
or the project checkout: each case runs in a disposable checkout the runner
clones at that revision and removes afterwards, so no flag is needed however
far the default branch has moved. --checkout-path overrides that tree and is
refused unless it sits at the candidate; --allow-tree-mismatch declares the
case reads nothing from the checkout.

For a deployment member whose cases require several Test Machines, the scoped
command automatically executes one immutable roster per machine. Each roster
holds its own lease and participates in that host's FIFO. It keeps the same
run, stage, member and frozen target, including cases on different plans.
A waiting host or independent review stops the command; after the wait or
review settles, rerun the same scoped command to continue the remaining hosts.
Completed scoped cases with passing evidence are retained. The member is
accepted only when every required case passes. Omit --machine for this
multi-machine form: a single host pin cannot satisfy conflicting constraints.

Who runs it, and what follows
-----------------------------
The item owner parked at its release wait runs its own stage when the
deployment wake asks for it, then finishes with `yoke merge item PREFIX-N
--result ... --verification ...`. The steering seat drives the run and never
substitutes a run-wide pass for a member's stage. See `yoke merge item --help`
for the close-out and `yoke deployment-runs --help` for the run itself.

Replacing a failed case with a corrected one
--------------------------------------------
When an admitted case failed because its capture or probe was wrong, create a
plan containing only its corrected case and name the failed requirement:

  yoke qa plan run --deployment-run-id RUN --stage STAGE [--member PREFIX-N] \\
      --plan CORRECTED_PLAN --project P --replaces CASE_KEY=FAILED_REQUIREMENT_ID

The failed attempt remains history and leaves the execution roster. The new
blocking case keeps the stage waiting until its independent verdict passes;
that pass supersedes the old row and resumes the run driver. A missing sibling
case still blocks. Retries reuse the declaration. To correct a failed
correction, name its requirement id. For an item subject, pass --replaces to
`yoke qa plan materialize --item PREFIX-N --transition T` before this run.
If the corrected direct requirement already exists, declare it with `yoke qa
requirement supersede --requirement-id FAILED_ID
--superseded-by-requirement-id CORRECTED_ID --rationale 'corrected case'
--declare-replacement`, then run the scoped plan without --plan. The old case
leaves its roster immediately; the corrected case still needs a pass.

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
same deployed revision:

  yoke watch qa-plan -- --deployment-run-id RUN --stage STAGE --member ITEM \\
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
