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

Before merge, direct Yoke lane-source commands use `yoke dev run -- <command>`.
Inside a post-deploy Command case, run `yoke watch pytest -- <test paths>`
directly: the QA runner supplies the candidate cwd and the watcher binds that
cwd to source. The candidate root and SHA travel to subprocesses in
`YOKE_QA_CANDIDATE_TREE`; source wrappers refuse a switch to a different root.
Candidate-bound Yoke cases also bind bare `python3` and `yoke` to candidate
packages and its declared locked .venv, recording interpreter identity and
import origins; missing/stale environments or outside-candidate origins
record a named refusal instead of a pass. Lane, external-project, and endpoint-only
`--allow-tree-mismatch` cases keep product imports.

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

A run that remains `pending` with zero jobs for 120 seconds is a stall candidate.
The waiter requires a complete GitHub concurrency-group listing with no configured
groups before naming it `ci_run_never_started`. Configured concurrency waits keep
being awaited until completion or the overall timeout; missing queue evidence is
a read error, never a stall. The gate force-cancels a confirmed stall and redispatches once without
another push. A run whose jobs were cancelled or failed to start before any
runner took them concludes as `ci_job_not_started`: a named no verdict, never a
test failure, redispatched once the same way. If the replacement also never
starts, the case fails immediately as `ci_job_not_started`; re-dispatch by
rerunning the same case, which starts a fresh run on the same commit rather than
rejoining the dead one. The worker never pushes by hand.

A project also declaring the merge-queue capability verifies
pull-request-first: after the shared rebase and single push, the executor opens
the landing pull request and records that pull request's own entry run as the
verdict, so one suite covers the gate and queue entry both. Expect the pull
request to be visible from verification onward — the merge phase enqueues that
one rather than opening another. A rebase conflict stops the gate before
anything is published; resolve it on the lane and re-run, which invalidates
nothing because no evidence exists yet.

## Manual project QA

For an operator-requested check outside an item's gates, run
`yoke qa plan run --plan PLAN --project P`. It records a standalone execution
and cannot satisfy this item's attached verification or delivery obligations.
Commands require a clean checkout and full SHA; CI requires a published ref at
that SHA and the case's named workflow. Machine, browser, and mission methods
retain their ordinary leases and reviews. Read `yoke qa plan run --help` for
source flags, abort, and continuation before executing.

## Materialize the attached plan and run its cases

Refresh `yoke workflows item get ITEM --json` and read its immutable pin with
`yoke workflows version get WORKFLOW_ID WORKFLOW_VERSION --json`. Set
`LIVE_STAGE` to the returned status and `NEXT_STAGE` to the unique declared
forward target whose `from_stage_id` equals `LIVE_STAGE` in
`definition.transitions`, ordered by `definition.stages`.
Confirm the active binding belongs to Dash. An absent or ambiguous forward
edge is `workflow_next_stage_ambiguous`: stop and ask the workflow owner to
repair or select the declared route. Use that target for QA and close review.

The preflight for the transition from `LIVE_STAGE` to `NEXT_STAGE` materializes every
effective plan attached at that stage into blocking case rows and only then
evaluates that stage's gates. Project defaults are effective only for workflow
QA policies that declare project defaults. Dash's `optional_item_attachment`
policy ignores them and has no definition-owned `qa_verification` done gate;
an item-specific verification posture still adds and enforces its own plan.
Run this whenever `qa_plan_attachments` in `yoke items detail get ITEM --json`
names a plan for `NEXT_STAGE`:

```text
yoke qa plan materialize --item ITEM --transition NEXT_STAGE --json
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

[Where a Browser case runs](../../../../.yoke/docs/reference/browser-scenarios.md#where-a-browser-case-runs)
places every Browser case. A `post_deploy` case bound to the release stage runs
after the deploy, not here. A pre-merge `verification` case at this transition
is captured against a target that serves **your committed candidate**, and the
case pins that candidate:

```text
yoke qa case run --requirement-id <requirement-id> \
  --base-url <candidate url> --expected-branch <lane branch> --expected-sha <lane HEAD>
```

The expected pair is checked by asking the target what it serves at
`/served-build`, so pass a target running this project's own build out of a
committed checkout — a static preview publishes nothing there. Commit before
starting that server: a checkout with uncommitted changes publishes
`<sha>-dirty` and fails the match closed. Without the expected pair the
capture records no commit, and the merge gate refuses it as `<missing>`;
against a target that publishes nothing the run refuses as
`identity_proof_unavailable` and records nothing at all.

Serving that candidate is project-specific. When you are working on Yoke's own
source, the source-dev doctrine names the review server that serves a claimed
lane on a spare port and publishes its commit.

Record that capture's review with one command, which resolves the capture in
place rather than opening an identity-less run beside it:

```text
yoke qa run record-verdict --requirement-id <id> --performed-by agent \
  --verdict pass --verdict-reason "what the screenshots showed"
```

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
attach it at the pinned definition's release stage (`RELEASE_STAGE`, resolved
from its stage with `board_bucket=release`), where post-deploy acceptance
binds. If the definition has no unique release stage, stop and ask the
workflow owner to resolve the attachment target:

```text
yoke qa plan create <slug> --project P --environment <env>
yoke qa plan-cases replace --project P --plan-id <id> --stdin
yoke qa item-plan attach --item ITEM --project P --plan-id <id> \
  --transition RELEASE_STAGE --qa-phase post_deploy
yoke qa plan materialize --item ITEM --transition RELEASE_STAGE
```

Its cases test **this item's** acceptance criteria — not another item's, and
not the release's in general. A Command case reads its own subject from the
environment the runner exports — `BASE_URL`, plus `DEPLOYMENT_RUN_ID` and
`DEPLOYMENT_MEMBER_REF` once the case is bound to a run and member — so never
write a run id or a member ref into the command as a literal: it would be
right for one release and quietly wrong for every one after. Materialize the
attached cases so the attachment is real: `qa plan run` refuses an empty
transition.

```text
yoke qa plan materialize --item ITEM --transition RELEASE_STAGE
```

**Do not try to run that plan here.** It is bound to the deployment
environment it was attached for, and `qa plan run` refuses a `--base-url`
outside that immutable target by name — your candidate is not that
environment until the release deploys it. A post-deploy plan is proven after
the deploy, at the stage that asks for it, and that is not a gap in your
verification: the pre-merge proof is the committed tree's own cases above.
What is worth doing here is reading the cases once as text, because a case
that names the wrong route or expectation is an edit now and a waiver later:

```text
yoke qa plan get <plan-id> --project P --full
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
  the stored instruction and actual target, placed where
  [Where a Browser case runs](../../../../.yoke/docs/reference/browser-scenarios.md#where-a-browser-case-runs)
  puts it. A change visible only once deployed takes a `post_deploy` case with
  `--target-env ENV --workflow-transition RELEASE_STAGE`; it binds the posture
  for review and the deployment stage executes it, so do not run it here. A
  pre-merge case binds to the review stage; execute the returned requirement:

  ```text
  yoke qa requirement add --item ITEM \
    --method-id <stored-method-id> --qa-phase verification \
    --workflow-transition NEXT_STAGE \
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
yoke lifecycle transition ITEM --from LIVE_STAGE --to NEXT_STAGE --reason "Implementation complete; verification passed"
```

Next: [`merge.md`](merge.md), or [`close-out.md`](close-out.md) for a
laneless or no-change result.
