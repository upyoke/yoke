"""Help text for ``yoke qa plan run``: the subject/scope matrix it teaches."""

#: The subject/scope matrix: which invocation credits which subject, and the
#: release-time form whose omission leaves a stage unsatisfied. Read as
#: ``yoke qa plan run --help``.
QA_PLAN_RUN_EPILOG = """\
Pick the subject, then the scope
--------------------------------
Exactly one subject flag is required, and it decides everything else.

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
--plan by name: a plan there materializes a second, duplicate set of
obligations beside the ones the stage credits. The wake asking for a selection
prints --plan; every other wake omits it.
Materialization stamps the run's own deployed target
onto the cases, so a plan authored before this release still verifies it. A
deployment case is bound to the candidate the run deployed, not to your lane:
pass --checkout-path at a separate checkout pinned to that revision, or pass
--allow-tree-mismatch when the case reads nothing from the checkout.

Who runs it, and what follows
-----------------------------
The item owner parked at its release wait runs its own stage when the
deployment wake asks for it, then finishes with `yoke merge item PREFIX-N
--result ... --verification ...`. The steering seat drives the run and never
substitutes a run-wide pass for a member's stage. See `yoke merge item --help`
for the close-out and `yoke deployment-runs --help` for the run itself.

Replacing a failed case with a corrected one
--------------------------------------------
When a case failed because the case itself was wrong (a capture that could not
establish the UI, a bad probe), materialize the corrected case with --plan and
name the exact failed requirement it replaces:

  yoke qa plan run --deployment-run-id RUN --stage STAGE [--member PREFIX-N] \\
      --plan CORRECTED_PLAN --project P --replaces CASE_KEY=FAILED_REQUIREMENT_ID

The failed case keeps blocking but is no longer captured or reviewed again, so
the review bundle holds only the newly captured cases. A passing independent
verdict on the corrected case supersedes the failed one in the same
transaction and the stage re-evaluates; a failing or undetermined one leaves
the failed case blocking with its evidence. To correct a failed correction,
name that correction's requirement id. For an item subject, pass --replaces to
`yoke qa plan materialize --item PREFIX-N --transition T` before this run.
"""


__all__ = ["QA_PLAN_RUN_EPILOG"]
