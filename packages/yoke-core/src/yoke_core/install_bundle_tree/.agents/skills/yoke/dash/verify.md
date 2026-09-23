# Dash phase 5 — bind the committed tree, verify, close review

## Iterate with the change-scoped check

Iterate with impacted-test selection over the branch diff
(`yoke watch pytest --impacted main --bounded` for this project) plus the
individual failing tests, as often as the work needs. `--bounded` keeps an
unbounded selection from widening to the full sweep: it reports
`selection unbounded (<rule>) — deferring full coverage to the final QA gate`
and runs the subset it could still compute. Read that as *keep testing what
you judge relevant*, not as a signal to run everything now.

Where the project declares a `ci_workflow_file` capability, commit; the gate
rebases onto the base branch, pushes once, and dispatches the selection
workflow. Do not push the lane by hand. Use that CI runner for normal
verification, broad selections, and selections of uncertain duration.
`--local` is only a small targeted check expected to finish in about one
minute for the entire invocation — one file or a small test count does not
prove a fast runtime, and uncommitted work does not justify a slow local run.
If a local check exceeds that, interrupt it cleanly, keep the capture as
incomplete, commit, and run the selection on CI; do not repeat or background
the slow local selection. Preserve `--local` for machine-specific diagnostics
and projects without CI.

The full-suite authority is CI on the protected merge path, which runs on the
pull request and again on the merged commit. Fall back to a local full sweep
only when CI is unavailable, and record that substitution in the verification
evidence. If CI fails a test the impacted run skipped, that is a selector
defect: fix the selection model in the same response, not just the code.

## Bind each case to a committed tree

**Commit before every SHA-bound QA case.** Resolve the exact touched set from
the worktree diff, then replace the survey with every actual file before
executing a case:

```text
yoke direct-workflow dash survey ITEM --path <actual-file> [--path <actual-file> ...] --json
yoke direct-workflow dash survey ITEM --no-changes --json  # genuine no-change only
```

A reported overlap remains advisory. Read the overlapping path, holding item,
and sanctioned routes. Proceed when the edits are independent. When they are
order-dependent, wait for the holding work to land (merge receipt, merged_at,
or git ancestry — not status) and re-run the survey; when they remain
unresolved, release the work claim and present the path, holder, and evidence
to the operator. The re-survey itself remains mandatory, but a contact does
not by itself prevent the commit or case.

Commit the coherent change in the worktree. Both the local `worktree_run`
runner and the remote `ci_run` runner record `verification_tree.head_sha`; the
merge and done gates compare that SHA to the committed tree. A local case can
execute dirty working-tree content while still recording the older HEAD, so
running it before the commit creates a passing but stale verdict. If the tree
changes after a case passes, re-survey, commit, and
rerun every affected SHA-bound case.

**The QA case run is the one full execution.** Do not run the project's full
sweep by hand and then hand the same tree to QA — the case executor re-runs the
identical registered command, so the verdict-producing run is the only one that
needs to happen. It streams live to stderr and prints its raw capture path
before starting, so you can follow it without a second copy. Re-running after
the tree changes is a different execution and stays required.

## When the committed case runs on CI

A project that declares its CI workflow binds its registered verification
scopes to the `command-ci` method. The executor rebases the lane onto the base
branch before resolving the verified SHA. For a merge-queue lane, it then runs
the local authored-file line cap against the refreshed base before publishing
anything. A base-caused overage names the file, resulting count, limit, and
base growth, then stops without pushing or opening the landing pull request. A
passing lane is published once and CI runs. Dash branches otherwise stay local
until this gate. The recorded verdict names the CI run URL and exact head SHA
it covered.

A run that remains `pending` with zero jobs for 120 seconds is
`ci_run_never_started`. The gate force-cancels it and redispatches once without
another push. If the replacement also never starts, the case fails immediately
with the same name and tells the worker to create an empty commit and rerun the
case so the gate pushes the new head; the worker still never pushes by hand.

A project also declaring the merge-queue capability verifies
pull-request-first: after the shared rebase and single push, the executor opens
the landing pull request and records that pull request's own entry run as the
verdict, so one suite covers the gate and queue entry both. Expect the pull
request to be visible from verification onward — the merge phase enqueues that
one rather than opening another. A rebase conflict stops the gate before
anything is published; resolve it on the lane and re-run, which invalidates
nothing because no evidence exists yet.

## Materialize the attached plan and run its cases

The `implementing` → `reviewing-implementation` preflight materializes every
effective plan attached at that stage into blocking case rows and only then
evaluates that stage's gates. Project defaults are effective only for workflow
QA policies that declare project defaults. Dash's `optional_item_attachment`
policy ignores them and has no definition-owned `qa_verification` done gate;
an item-specific verification posture still adds and enforces its own plan.
Run this whenever `qa_plan_attachments` in `yoke items detail get ITEM --json`
names a plan for `reviewing-implementation`:

```text
yoke qa plan materialize --item ITEM --transition reviewing-implementation --json
yoke qa requirement list --item ITEM --json
```

Execute every unsatisfied, non-waived requirement the listing returns for
that transition through the registered case runner, and retain the passing
runs:

```text
yoke qa case run --requirement-id <requirement-id>
```

An empty listing means no effective plan is attached at that transition. For
optional Dash QA that is an honest absence; do not invent a substitute command
or a hand-written run.

## Say what your deploy needs verified

When the item's resolved deployment flow carries an **item-scoped QA stage**,
that stage will later ask this item to prove its own behaviour on the deployed
candidate. `yoke merge item` asks you first, and refuses the landing until you
answer — the resolved flow being the one that will close the item, so an item
that never pinned a flow is still asked through its project's delivery default.

Two answers are durable and they are different. If there is genuinely nothing
to check once this item is live, record that no post-deploy obligation
exists, and why, and merge:

```text
yoke qa post-deploy record-no-obligation --item ITEM --reason "why nothing is observable once deployed"
```

That is an answer, not a bypass and not a waiver: it writes the item's
no-obligation fact, the deployment QA stage discharges on it, and a reader
listing waivers will not see it. `yoke qa post-deploy declare-none` remains
the waiver for declining a check that might have been done. Do not reach
for either to get past the refusal when the item has something to verify
and no plan — that is the case this whole gate exists for.

Otherwise author that plan here, while its cases are still editable, and
attach it at the item's release stage, which is where post-deploy
acceptance binds:

```text
yoke qa plan create <slug> --project P --environment <env>
yoke qa plan-cases replace --project P --plan-id <id> --stdin
yoke qa item-plan attach --item ITEM --project P --plan-id <id> \
  --transition release --qa-phase post_deploy
yoke qa plan materialize --item ITEM --transition release
```

Its cases test **this item's** acceptance criteria — not another item's, and
not the release's in general. A Command case reads its own subject from the
environment the runner exports — `BASE_URL`, plus `DEPLOYMENT_RUN_ID` and
`DEPLOYMENT_MEMBER_REF` once the case is bound to a run and member — so never
write a run id or a member ref into the command as a literal: it would be
right for one release and quietly wrong for every one after. Materialize the
attached cases before the dry run; `qa plan run` refuses an empty transition.
Then dry-run the plan once against your own candidate, before merging, while a defect still
costs an edit:

```text
yoke qa plan run --item ITEM --transition release \
  --base-url <your candidate>
```

`yoke merge item` refuses an item whose flow has an item-scoped QA stage and
has neither attached a plan nor declared it needs none, and names both
recipes. An item whose flow has no such stage is unaffected and needs none of
this. The deployment stage picks the attached plan up on its own, so nothing
has to be chosen at the wake — which is the point: a probe first executed
against production, after its case has frozen, can only be waived or
superseded.

Selecting a plan with `--plan` on a running deployment stage is a third,
different thing: it binds cases to that one run and writes nothing the item
keeps, so the next deployment is back to having no answer. Attaching is what
makes the answer standing.

## Posture knobs

Then execute each selected posture knob through its shared authority:

- `verification.kind=plan` — the materialize-then-run pass above is that
  execution. Confirm the passing rows are the selected plan's, because the
  posture gate reads only requirements carrying that `plan_id`.
- `verification.kind=ad_hoc` — author the concrete selected-method case from
  the stored instruction and actual target, then execute the returned
  requirement:

  ```text
  yoke qa requirement add --item ITEM \
    --method-id <stored-method-id> --qa-phase verification \
    --workflow-transition reviewing-implementation \
    --instructions "<instruction applied to the actual target>" \
    --expected-outcome "<observable passing result>" \
    --method-config '<method-specific JSON>'
  yoke qa requirement get --requirement-id <requirement-id>
  yoke qa case run --requirement-id <requirement-id>
  ```

- `file_budget` — when selected, confirm the persisted budget covers actual
  edit targets and remains useful sizing/conflict evidence;
- `path_claims` — when selected, the lifecycle gate requires active concrete
  coverage now and compares merged touched-file evidence with it at done;
- `approval_on_done` — the final transition creates a project-owner decision
  request and stays blocked until an authorized owner approves it;
- `deployment` — after merge, run the selected/default item-bound project flow
  for the recorded merge identity and wait for status `succeeded`.

Posture can tighten execution; it cannot remove a workflow gate or a governed
migration invariant.

## Close review

Move into the verification-close stage only when implementation checks pass
and every case materialized above carries a passing run — the transition gates
on those rows, so it is the last step of this section, never the step that
discovers them. The merge boundary refuses to land a branch before this
transition, `--skip-status` included, so it is also not a step to defer:

```text
yoke lifecycle transition ITEM --from implementing --to reviewing-implementation --reason "Implementation complete; verification passed"
```

Next: [`merge.md`](merge.md), or [`close-out.md`](close-out.md) for a
laneless or no-change result.
