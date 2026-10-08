### 6. Deploy merged work in batches

Workers merge but never create or dispatch deployment runs. The steerer owns batch delivery through the **prod control-plane** connection even when the target environment is stage.
Ordinary external delivery works over HTTPS. When steering a Yoke source release, read [source-dev-delivery.md](source-dev-delivery.md) before creating or driving its self-deploy pair.

**Take the project's deploy lock before the first run and hold it through the
whole pair.** Creating a run and executing one both refuse without it, so one
seat drives a project's deployments and a stage promotion cannot overtake the
production promotion it precedes:

```text
yoke claims coordination-claim acquire --project {_project} --key DEPLOY:{_project} --reason "driving the release pair"
```

Before creating the pair, read each delivery-ready item's selected completion
flow (`yoke items detail get PREFIX-N --json`) and the intended flow's bound
projects (`yoke deployment-flows stages {FLOW}`). Select the member flow for
same-project final delivery. A bound-project member can close through the
carrying run when that run ships its project's source. If selections differ,
use a run of the items' selected flow or deliberately reconcile those item
flows, then validate composition; never silently rewrite a selection.

Pin one source SHA and use that same SHA for stage and production. On a flow
that waits for CI it must have its own CI run, and a merge-queue push tests
only its newest commit: create the CI-gated production run without
`--source-ref` so it binds the newest tested first-parent commit on the gate
branch (or dispatches CI there when no commit has a run and binds the commit
that run tests; a selection off the previous release's lineage is refused
`release_source_off_lineage` naming both commits), read it with `yoke --env <cp> deployment-runs get {RUN_ID}
release_lineage`, and pass it as `{PINNED_SHA}` for the stage run, which
refuses a missing lineage. An untested `--source-ref` is refused
`release_source_untested` with the newest tested commit named; a gate that
still finds no run fails by name, and the recovery is a new run, never a hand
dispatch:

```text
yoke --env <cp> deployment-runs create {_project} {PROD_FLOW} --environment prod --idempotency-key prod-{PROD_FLOW}-1
yoke --env <cp> deployment-runs create {_project} {FLOW} --environment {ENV} --project-repo-path {CHECKOUT} --source-ref {PINNED_SHA} --idempotency-key {ENV}-{PINNED_SHA}-1
yoke --env <cp> deployment-runs validate-composition {RUN_ID}
yoke --env <cp> watch deploy -- {RUN_ID}
```

Creation pins bound sources and provisionally composes every delivery-ready
item the candidate carries that no live or succeeded release holds, a landing
behind the last release included. Its validation refuses all independently
detectable blockers before committing a run ID; start validates again before
dispatch. `yoke --env <cp> deployment-runs add-item {RUN_ID} PREFIX-N`
is for the other case — an item whose code the candidate does not carry but
which the run should still deliver — and `... validate-composition {RUN_ID}`
composes the run now. Both hold the same deploy lock
and refuse an item whose project the run ships no source for, an incompatible
flow binding, or enrollment after the run has left `created`. Composition names
every carried item it skipped — held by another release, back in rework before
its release stage, or removed — in one notice. The production half holds its
members only for production, so the stage run on `{PINNED_SHA}` still enrolls
each one owing stage QA; a stage run on any other commit skips them, naming
the commit production pinned, because only same-commit stage proof credits. A member composed by mistake
comes out of a still-`created` run with `yoke --env <cp> deployment-runs
remove-item {RUN_ID} PREFIX-N --reason R`, never by cancelling the pair: the
reason is recorded on the run and composition does not re-enroll it.

**A run can deploy a second project's code without carrying its items.** A
`github-actions-workflow` stage may declare an `input_bindings` map, resolving
another registered project's branch tip during composition and shipping that commit
alongside this run's own candidate. The binding is the only place this is
stated, so read it before planning either project's release:

```text
yoke deployment-flows stages {FLOW}
```

Membership follows that code: the run resolves each bound branch once during
composition and records the commit, so the bound project's delivery-ready items are
enrolled against that exact commit and closed out by the run that actually
shipped them. An item whose project the run ships no source for is still
refused, and stays at its release wait until a run that does ship its code
carries it. Check the ordering either way: work merged after the binding
resolved did not ride, and genuinely needs its own run.

Retry from the recorded run instead of silently creating unrelated lineage:

```text
yoke --env <cp> deployment-runs create {_project} {FLOW} --retry-of {RUN_ID} --idempotency-key retry-of-{RUN_ID}-1
```

A create that yielded is still running — continue that invocation; only if it
exited without a run id, repeat it verbatim with the SAME key to get the
original run back. A new key is a deliberate new run.
A retry copies the frozen bound sources, so when a bound stage fails before
dispatch with `bound source ... is stale`, or the failure trace prints
`Stale bound source: ...`, neither re-drive nor `--retry-of` can pass: create
a new run, which binds the current commit.

For red member QA, `yoke deployment-runs remove-item RUN ITEM --reason R` lets an independent run finish while the member waits for its next release; see `remove-item --help`. Settlement automatically releases members whose current candidate is outside the frozen lineage.

**A member's item QA is that member's own, not yours.** A QA stage is credited
only by requirements bound to its own stage name — an item-scoped one by ones
bound to the member too — so a run-wide pass you issue records nothing the
stage counts. The deployment wake re-enters each parked owner on a natively
wakeable surface for its stage; an owner whose surface's wake authority is
operator (a desktop app) is never resumed by Yoke, so ask its operator to
re-enter it. The owner runs its own:

```text
yoke watch qa-plan -- --deployment-run-id {RUN_ID} --stage STAGE --member PREFIX-N --project {_project}
```

Broadcast that exact form if an owner asks which command to run; never an
unscoped `yoke qa plan run --deployment-run-id {RUN_ID}` and never
`yoke qa case run --requirement-id N`, both of which leave the stage
unsatisfied. Depth: `yoke qa plan run --help`.

System-owned waits wake their owners; a missing wake is a defect.

Add `--plan PLAN` to the scoped QA command only when the stage names no
cases and asks the agent to select them. A selected stage already has its
own cases. Completed scoped execution settles the stage acceptance on the
server and opens its configured human review immediately. A resolved review
also reaches this run's driver; re-enter the pinned runner on the same run
after a continuation notice, without repeating passing QA or deployment
stages. A member settling while its stage still waits on others sends the
seat no notice: the fleet report's run row shows which members still owe QA,
and a notice arrives when the stage settles, goes red, or its automatic
continuation fails.

**The deploy driver owns run-scoped visual QA.** Inspect the run's live
target as an agent, or assign a capable QA agent through Yoke. Record the
inspection and verdict against that run and stage:

```text
yoke watch qa-plan -- --deployment-run-id {RUN_ID} --stage STAGE --project {_project}
```

Add `--plan PLAN` only when this run stage names no cases. Then re-drive
`{RUN_ID}` through its existing pinned runner. Item QA evidence has its own member subject and cannot credit this run-scoped stage.
A case that failed because the case itself was wrong is corrected with a plan containing only its corrected case: `--plan CORRECTED --replaces CASE_KEY=FAILED_REQUIREMENT_ID`. This correction is allowed even when the stage names admitted cases. The failed case leaves the roster and is superseded when the correction passes review, so never supersede it by hand.

Item-scoped QA acceptance triggers automatic member close-out. A final member on a selected flow without run QA or run approval closes from its
landing and final production QA acceptance or explicit
`post_deploy_no_obligation` discharge while sibling item QA keeps the run
executing. A flow with run QA or run approval holds every final member through all
item QA, shared gates, and run success. Automatic close-out ends an otherwise
empty holder session. Do not
acquire a live owner's claim to finish its item, and do not reach for the
internal done engine — `done-transition --skip-deploy` records a selected-flow
delivery as out-of-band, which is a false record and is refused when the item's
flow already has a succeeded run covering its merge.

Only an ORPHANED member is yours to finish — one whose owner the stale sweep
reclaimed and handed to this seat by name. Take the claim and run the same
close-out every owner runs:

```text
yoke claims work acquire --item PREFIX-N --reason "orphaned release-wait member"
yoke merge item PREFIX-N --result "<what shipped>" --verification "<run evidence>"
```

Release the claim only if that close-out did not already release it. An item
parked at release still holds path claims and blocks dependents until it
reaches `done`. Depth: `yoke merge item --help`.

Then release the deploy lock, so the next seat can drive:

```text
yoke claims coordination-claim release --project {_project} --key DEPLOY:{_project} --reason "release pair complete"
```

Nothing reclaims that lock automatically. After confirming the pipeline settled,
a signed-in human outside any harness session runs `yoke coordination-claim
release --project P --key DEPLOY:P --claim-id N --holder-session-id S --reason
"..."`; HTTPS/local authority, exact-holder refusal, reason, and WARN audit apply.
