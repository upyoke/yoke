# Deployment QA Stage Execution

Schema-2 deployment flows may pause on ordered QA stages whose durable subject
is the frozen deployment run, stage name, and optional attached member. These
stages reuse `qa_plan_executions` for roster/cursor ownership,
`qa_requirements` for concrete obligations, and `qa_runs` plus `qa_artifacts`
for evidence. They do not create another release, scheduler, or verdict store.

Run scope executes once for the combined release. Item scope executes once per
frozen member against the same deployed preview, stage, or production target:

```text
yoke qa plan run \
  --deployment-run-id <run-id> \
  --stage <stage-name> \
  [--member <PREFIX-N>] \
  [--plan <agent-selected-project-plan>] \
  --project <project>
```

The member flag is required for item scope and forbidden for run scope. Named
flow cases and selected member requirements come from the run's immutable
admission snapshots. If no concrete method case was admitted or configured,
the executor supplies `--plan`; its frozen cases are materialized separately
from admitted aggregate obligations, so evidence retains both identities.

`--plan` is only for that empty stage. A subject already naming cases —
pinned in the stage config, frozen into the run or member snapshot, attached
to the member, admitted from the member's own post-deploy obligations,
authored directly onto the stage, or materialized by an earlier selection —
refuses `--plan` by name, because a plan there materializes a second set of
obligations beside the ones the stage credits and the stage then waits on
both. The wake that wants a selection prints `--plan` in its recipe; every
other wake omits it. Correcting an already-materialized selection is
`yoke qa plan rematerialize` below, not a second run.

A direct admitted copy belongs to no plan and stores no case/baseline positions.
The roster assigns its order; stored positions instead trigger plan drift at
execution begin: "this requirement joined a plan after the roster froze".

Every requirement and execution carries `deployment_stage`; item scope also
carries `deployment_member_item_id`. Legacy deployment-run rows keep both NULL.
Each QA target names `source_stage`, an earlier non-QA stage whose executor
produces a durable `deployment_stage_receipts` attempt before dispatch. Attempt
numbers are allocated under the run lock; a repeated correlation ID is
idempotent only when its immutable dispatch inputs match. The latest attempt is
authoritative even when an older callback arrives later. Only a latest `ready`
attempt with the exact target and release lineage can start QA; when the run
pins an artifact identity, the receipt must observe that exact artifact too.
Run-preview receipts must also carry the observed URL; command-only persistent
targets may omit one.

Materialization records the resolved tenant, project, configured environment,
site and endpoints together with the receipt ID, attempt, correlation, observed
URL/revision/artifact, run, QA stage, member, `release_lineage`, and artifact
identity in the existing execution-target snapshot. Generic projects resolve
their registered environment settings; there are no Yoke-hostname or fixed
stage/production assumptions. Every execution and result write re-resolves the
frozen receipt and refuses if it was superseded, failed, cancelled, changed
target, or changed candidate. Historical evidence stays attached to the old
execution and cannot settle a replacement or satisfy a later-stage prerequisite.

All concrete blocking cases must pass with evidence attached to the exact
execution capture, or carry an explicit discharge, before stage acceptance.
Admitted aggregate obligations require their own explicit passing result linked
to evidence artifacts from concrete cases in that execution; case success is
never copied into an automatic obligation pass. `agent_only` requires a
conclusive agent verdict.
`human_if_unsure` creates authorized Inbox work only after an evidence-backed
undetermined case verdict. `required_human` waits until every case passes, then
creates one whole-stage acceptance request using the configured project roles,
named actors, and ANY/ALL mode. Neither request is created while an artifact it
would show is unreadable where the reviewer looks: the stage answers blocked
with `evidence_not_portable`, names each artifact, and gives the
`yoke qa artifact rehome` recovery (see
[Evidence portability](../testing-verification/evidence-portability.md)).
Item-stage acceptance for every member is a
hard prerequisite for later run-scoped QA. Resume/from-stage and flow failure
policy cannot skip these acceptances.

Advanced definitions remain disabled while
`CURRENT_EXECUTION_SCHEMA_VERSION` is 1. Enabling schema 2 belongs to the
coordinated lifecycle/runtime rollout after its consumers are verified. The
receipt table and read/write contract are additive, but no current flow writes
receipts until that rollout lands its executor integration.

## Correcting a case, and discharging one that cannot be corrected

A run-bound case is a frozen acceptance snapshot, but the freeze starts when
the case answers, not when it is materialized. Until it records a `pass` or
`fail`, `yoke qa requirement update --field method_config` corrects it in
place. That window exists because the defects worth catching are not visible
in the case text: materialization already rejects a case pinned to another
environment's endpoints or one whose configuration breaks its method
contract, so what is left — a probe asserting a response field the endpoint
does not project, a case asserting data the environment does not have — only
appears the first time the case runs against the real deployed target. An
`undetermined` or `error` verdict does not close the window; neither reached
a judgement.

A plan-owned member requirement is admitted through its plan snapshot, preserving
case and host-baseline positions. Close-out finds its copies by plan id and
case key on the completion run and source member. Stage acceptance is required,
and every host copy must pass or be discharged. Direct sources use their
source key on that same run/member. Plan-less grouped hosts need an attached plan.
A plan-less obligation is copied under `admitted-requirement-<source id>`, so correcting the item
row and correcting what the stage runs are two different writes. They are
reconciled rather than left to drift. `yoke qa requirement update` resolves
the source row's admitted copies and, for each one on a run that is still
active, either reaches it or refuses:

- a copy that has not yet recorded a determinate verdict is corrected with the
  source, on the same correction-window rule — a case nobody has judged is a
  case, not a result, so nothing is rewritten;
- a copy that has already answered, or that a live execution has frozen into
  the roster it is being walked against, refuses the amendment as
  `admitted_copy_in_flight` **before either row is written**, naming the copy,
  its run, and the recovery: abort that execution, re-apply the amendment so
  it reaches the copy, and start the stage again — or, for a copy that
  answered, supersede it;
- a copy whose own obligation is already **settled** — waived, or superseded
  by a corrected case that carries the obligation now — is not reconciled and
  does not refuse. Nothing is waiting on it, so it has no claim to hold its
  source row still. Reading only the waiver here closed the exit the supersede
  receipt names: the operator superseded the frozen copy exactly as the
  refusal above instructed, then found correcting the source refused because
  of that same copy, sent back to the supersession they had just recorded;
- a copy on a terminal run is left alone. It is the acceptance record of what
  that release was judged against, and rewriting it would be the corruption
  the freeze exists to prevent.

Reconciliation covers the fields that decide what a case *executes*.
`target_env`, `qa_phase` and `qa_kind` are excluded on purpose: admission
rewrites them to the stage's own target, so an item's values there would break
the copy rather than correct it.

Whatever route a divergence arrives by — a row that diverged before this
reconciliation existed, or an amendment through a path that does not resolve
copies — the stage refuses rather than certifies. Building an execution roster
and every case begin check the copy against its live source and raise
`admitted_case_superseded`, naming both requirement ids and the fields that
moved. A stage that cannot run the current definition says so by name; it
never quietly runs the old one.

That refusal names the recovery that exists, which depends on what moved and
on what stands behind the source row. Reconciliation can only reach a field
`yoke qa requirement update` accepts, so a divergence confined to those is
repaired by aborting the execution and re-applying the amendment.
`instructions` and `expected_outcome` are not on that allowlist.

When the source row was materialized from a QA plan, `yoke qa plan
rematerialize` is still the answer for those fields: it rewrites the source
from the plan and carries that same body onto the copy, so both come current
together. The refusal names that exact invocation, chosen from the row's own
subject. See [Plan case currency](plan-case-currency.md) for the plan-to-row
link and where that refresh refuses in turn.

When no plan stands behind the source, its prose can be written by no path at
all, and telling an operator to refresh it would teach an action nobody can
perform. For that divergence the refusal says so and names the three remedies
that do exist: supersede the copy with a corrected case bound to the same run,
stage, member and target; waive it through the registered waiver surface with
explicit authorization; or deliver the item on a new run, whose admission
freezes the corrected body.

`yoke qa requirement list --deployment-run-id <run-id>` reports
`source_currency` (`current` or `stale`), `source_requirement_id`, and
`source_diverging_fields` for every admitted copy, so whether a running case
is the item's current definition is readable from the run without opening the
item's row beside it.

Relatedly, a Command case that reads `BASE_URL` must set
`method_config.requires_base_url`. The runner injects `BASE_URL` only for a
case that declares it, so an undeclared probe does not fail — it falls
through to whatever default it hardcodes and quietly tests a different
environment than the stage deployed.

When the plan itself was corrected, refresh the whole subject rather than
each row:

```text
yoke qa plan rematerialize --deployment-run-id <run-id> --stage <stage-name> \
  [--member <PREFIX-N>] [--plan <plan>]
```

A materialized case is unique on
`(run, stage, member, plan_id, plan_case_key, host_baseline, target)`, so a
corrected plan case cannot arrive as a second row under the same key —
refreshing in place is the route, and before this there was none for a
deployment subject at all. Authority follows the subject, as it does for
`yoke qa plan materialize`: an item-scoped stage checks the member's claim,
resolved from `--member`, since a deployment target carries no item of its
own; a run-scoped stage has no member to claim, so the run itself authorizes
the refresh and a run's QA agent can follow the recovery a plan edit printed.
The refresh keeps the deployment target the stage receipt pinned; it never
re-points a frozen run at whatever environment the plan names today. It
refuses as a whole, naming each row, when any case in the subject has already
answered, rather than leaving the stage half refreshed.

Selecting a plan on a stage that pins no cases is the other correction route.
Materialization there is idempotent per plan, which used to strand a member:
once its only row was waived, a corrected case could not reach it, because the
discharged row satisfied idempotency. Now a case materializes again when both
halves hold — the existing rows no longer answer (waived, superseded, or a
settled `fail`) and the case's executable content has changed since it was
materialized. The corrected row takes a key carrying that content's digest, so
it sits beside the frozen one rather than replacing it, and is declared the
replacement of every earlier row for that case that failed without being
settled (see *Declared replacement* below). An unchanged case stays idempotent however its row was
discharged, and a case whose row is still answering never gets a second row
racing it. When that still-answering row has not been judged and its case
changed, materialization refuses as `plan_case_superseded` rather than walk
the replaced content, naming the `yoke qa plan rematerialize` that brings it
current.

Once a case has answered, its snapshot is frozen for good and there are two
discharges, both recorded and both distinguishable from a passing result.
The usual route to the first is declaring the replacement when the corrected
case is materialized:

- **Declared replacement.** Materialize the corrected case and name the exact
  failed requirement it replaces:

  ```text
  yoke qa plan run --deployment-run-id RUN --stage STAGE [--member PREFIX-N] \
    --plan CORRECTED_PLAN --project P --replaces CASE_KEY=FAILED_REQUIREMENT_ID
  ```

  (`yoke qa plan materialize ... --replaces` declares without running; an
  item subject declares there before `yoke qa plan run --item`.) The failed
  row records `replacement_requirement_id` and keeps blocking, but no later
  execution captures or reviews it again, so the review bundle holds only the
  newly captured cases. When the corrected case records a passing independent
  verdict — the agent review batch, or a human approving its review — the
  failed row is superseded on that verdict's own transaction, before the stage
  settles, so the stage re-evaluates and asks for any human acceptance it
  requires without anyone superseding by hand. A failing or undetermined
  verdict supersedes nothing: the failed row keeps blocking with its evidence
  and the corrected row fails for itself. To correct a failed correction,
  declare the new case the replacement of that failed correction; every row
  still waiting on it moves to the new case. The declaration refuses a key
  matching no case (or several) among the cases that materialization produced,
  a failed row that already passed or is already settled, and a replacement
  outside the failed row's run, stage, member and target. Earlier attempts
  stay as history: the web views show a waiting row as an *earlier attempt*
  and a discharged one as *superseded* by the case that passed in its place.
- **Supersession.** A corrected case bound to the same run, stage, member and
  execution target (for an item case: the same item, transition, phase and
  target), which has itself passed, is recorded as answering the broken case's
  obligation. A declared replacement records this automatically; by hand:

  ```text
  yoke qa requirement supersede --requirement-id <frozen-id> \
    --superseded-by-requirement-id <corrected-id> --rationale "<why>"
  ```

  The superseded row is left exactly as it is, so what went wrong stays
  readable. The superseding row is graded on its own evidence in the same
  pass, so a link cannot carry a failure through. Supersession is run-local
  and never reaches the item requirement an admitted copy was frozen from —
  that row is a real outstanding obligation, and discharging it from here
  would drop it forever — so when the discharged case is an admitted copy the
  receipt returns `admitted_from_requirement_id` and a `next_admission_notice`
  naming that row and the `yoke qa requirement update` that corrects it.
  Without it the correction reaches one run and the next release admits the
  same body again. A source that is missing, or itself already discharged, is
  named by neither, because no future release admits it. Supersession refuses a
  replacement in another subject, one that is non-blocking, waived, already
  superseded, or that has not recorded a passing verdict. A case's evidence is
  counted first on the run whose verdict the gate accepted — the newest run
  for that requirement, which is where a reviewer attaches evidence — and then
  through any completed execution of that same subject and target, not only
  the newest one. Both halves are load-bearing: asking only the execution
  record named the capture run it wrote and refused a member whose evidence
  was attached to the accepted pass, while a corrected case normally runs
  under its own plan and therefore its own execution, and reading a single
  execution made such a case report "no attached evidence" and hold the stage
  it had just satisfied. A pass carrying artifacts on no run at all still
  refuses, and that refusal names every run id it inspected plus the run to
  attach evidence to.
- **Waiver.** `yoke qa requirement waive --force` remains the authorized
  operator discharge when no corrected case answers.

A stage subject whose every blocking case is waived or superseded has nothing
left to execute, so it is **discharged**: it gates exactly like `accepted`,
and reads as `discharged` wherever a state is rendered — including the stage
result notice sent to the member's owner. Keeping the two words apart is
deliberate; an authorized discharge is not a result that passed. A subject
with no materialized cases at all is unanswered unless the member recorded
that it has no post-deploy obligation (not a waiver) or a waiver-backed
declaration before the deploy.

## Failed member QA handoff

A completed item-scoped execution with a determinate failing case sends a
notice to that member's work-claim holder. If the holder is gone, the notice
uses the **member's project** steering seat, even when the run carries members
from several projects. The one-line notice names the run, stage, member and
failed requirement ids, then points to `yoke qa plan run --help` for the full
recovery recipe. It skips verdicts produced by the recipient session, which
already holds the result. A repeated
check of the same failed verdict deduplicates; a new failed verdict or run
can send a fresh handoff. If nobody is addressable, the stage remains blocked
and the runner names the missing recipient so the member can be staffed.

The evidence decides the route. An environment or asset-delivery failure is
retryable against the same deployed revision: leave the item in `release` and
run fresh QA with `yoke watch qa-plan -- --deployment-run-id RUN --stage STAGE
--member ITEM --project PROJECT`. A member code defect uses the pinned
workflow's ordinary backward transition, `yoke lifecycle transition ITEM
--from release --to implementing --reason "..."`, without an operator
approval step. Refresh any conflict survey its activation gate requires.
Keep the existing claim and worktree, correct and verify the item, then merge
it again. The run driver settles the old run without changing its pin. The
failed run and QA stay as history; its frozen candidate cannot be rewritten,
so a new run delivers the corrected commit.

## Carried item approval before shared acceptance

For a final-delivery run with human run QA or a human approval stage, each
final member's declared done approval is requested under that member's own
project and pinned workflow before the shared human request opens. Run QA
capture and agent review may continue while those item decisions wait. A
rejected item decision blocks shared acceptance and names the member and
request; the item needs correction through its ordinary workflow before a
new approval can be requested. Resolving the last required item decision
revisits the run automatically, including a run already at finalization.

Shipping and Runs select whole runs by a carried member's project. The run
card and detail show every member, check, pending or resolved decision, and
its evidence, even when the selected project is only one part of a mixed
run. An itemless run belongs to its owning project for this selection. Run
detail has no project selector; the Runs list retains its selector. Inbox
keeps its ordinary project filter. The evidence gallery expands across the
available width, with its Show less control after the full expanded set.

## Governed cutover

Migration `0043_scoped_deployment_qa_execution` adds nullable stage/member
columns, replaces only recognized legacy subject checks, and replaces the old
run-wide active/materialization indexes with separate legacy, run-stage, and
member-stage partial unique indexes. It rewrites no historical row. Its serving
floor is `NEXT_RELEASE` because an old boot can recreate the retired run-wide
index.

Permitted deployment order is: drain every old serving build; boot the new
release so additive convergence runs; apply the ordered migration; then admit
scoped writers after exact hosted-consumer verification. A binary-only rollback
after migration is forbidden. To return to old binaries, stop the new build and
restore the pre-migration database backup first.
