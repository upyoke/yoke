### 4. Execute the instruction

Make the smallest complete change. Preserve unrelated work. Apply the
repository's simplify doctrine and governed database rules. Run focused
checks while editing. Capture every non-trivial test or build before
inspecting its tail.

If the instruction is investigative, the durable result may be a
well-grounded no-change finding. Do not invent a code change merely to
produce a diff. Record that exact outcome with
`yoke direct-workflow dash survey ITEM --no-changes --json` wherever the
sequence below requires the actual touch set; never substitute a placeholder.

### 5. Bind the committed tree, verify, and close review

Iterate with the change-scoped check — impacted-test selection over the
branch diff (`yoke watch pytest --impacted main --bounded` for this
project) plus the individual failing tests — as often as the work needs.
`--bounded` keeps an unbounded selection from widening to the full sweep:
it reports `selection unbounded (<rule>) — deferring full coverage to the
final QA gate` and runs the subset it could still compute. Read that as
*keep testing what you judge relevant*, not as a signal to run everything
now. Where the project declares a `ci_workflow_file` capability, commit;
the gate rebases onto the base branch, pushes once, and dispatches the
selection workflow. Do not push the lane by hand. `--local` runs the check
here instead, under one machine-wide xdist worker budget. The full-suite
authority is CI on the protected merge path, which runs on the pull request
and again on the merged commit. Fall back to a local full sweep only when CI
is unavailable, and record that substitution in the verification evidence.
If CI fails a test the impacted run skipped, that is a selector defect: fix
the selection model in the same response, not just the code.

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
not by itself prevent the commit or case. Commit the coherent change in the
worktree. Both the local `worktree_run` runner and the remote `ci_run` runner
record `verification_tree.head_sha`; the merge and done gates compare that SHA
to the committed tree. A local case can execute dirty working-tree content
while still recording the older HEAD, so running it before the commit creates
a passing but stale verdict. If the tree changes after a case passes,
re-survey, commit, and rerun every affected SHA-bound case.

**The QA case run is the one full execution.** Do not run the project's
full sweep by hand and then hand the same tree to QA — the case executor
re-runs the identical registered command, so the verdict-producing run is
the only one that needs to happen. It streams live to stderr and prints
its raw capture path before starting, so you can follow it without a
second copy. Re-running after the tree changes is a different execution
and stays required.

**When the committed case runs on CI, let the executor publish it.** A project
that declares its CI workflow binds its registered verification scopes to the
`command-ci` method. The executor rebases the lane onto the base branch before
resolving the verified SHA. For a merge-queue lane, it then runs the local
authored-file line cap against the refreshed base before publishing anything.
A base-caused overage names the file, resulting count, limit, and base growth,
then stops without pushing or opening the landing pull request. A passing lane
is published once and CI runs. Dash branches otherwise stay local until this
gate. The recorded verdict names the CI run URL and exact head SHA it covered.

A run that remains `pending` with zero jobs for 120 seconds is
`ci_run_never_started`. The gate force-cancels it and redispatches once without
another push. If the replacement also never starts, the case fails immediately
with the same name and tells the worker to create an empty commit and rerun the
case so the gate pushes the new head; the worker still never pushes by hand.

A project also declaring the merge-queue capability verifies
pull-request-first: after the shared rebase and single push, the executor opens
the landing pull request and records that pull request's own entry run as the
verdict, so one suite covers the gate and queue entry both. Expect the pull
request to be visible from verification onward — step 7 enqueues that one
rather than opening another. A rebase conflict stops the gate before anything
is published; resolve it on the lane and re-run, which invalidates nothing
because no evidence exists yet.

**Materialize the attached plan and run its cases before the transition.**
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

Move into the verification-close stage only when implementation checks pass
and every case materialized above carries a passing run — the transition gates
on those rows, so it is the last step of this section, never the step that
discovers them:

```text
yoke lifecycle transition ITEM --from implementing --to reviewing-implementation --reason "Implementation complete; verification passed"
```
