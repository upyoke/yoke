### 4. Execute the instruction

Make the smallest complete change. Preserve unrelated work. Apply the
repository's simplify doctrine and governed database rules. Run focused
checks while editing. Capture every non-trivial test or build before
inspecting its tail.

If the instruction is investigative, the durable result may be a
well-grounded no-change finding. Do not invent a code change merely to
produce a diff.

### 5. Bind the committed tree, verify, and close review

Iterate with the change-scoped check — impacted-test selection over the
branch diff (`yoke watch pytest --impacted main --bounded` for this
project) plus the individual failing tests — as often as the work needs.
`--bounded` keeps an unbounded selection from widening to the full sweep:
it reports `selection unbounded (<rule>) — deferring full coverage to the
final QA gate` and runs the subset it could still compute. Read that as
*keep testing what you judge relevant*, not as a signal to run everything
now. The full-suite authority is CI on the protected merge path, which
runs on the pull request and again on the merged commit. Fall back to a
local full sweep only when CI is unavailable, and record that
substitution in the verification evidence. If CI fails a test the
impacted run skipped, that is a selector defect: fix the selection model
in the same response, not just the code.

**Commit before every SHA-bound QA case.** Resolve the exact touched set from
the worktree diff, then replace the survey with every actual file before
executing a case:

```text
yoke direct-workflow dash survey ITEM --path <actual-file> [--path <actual-file> ...] --json
```

If the survey is blocked, do not commit or run the case. Coordinate, wait,
tighten with claims, or escalate. When it is clear, commit the coherent change
in the worktree. Both the local `worktree_run` runner and the remote `ci_run`
runner record `verification_tree.head_sha`; the merge and done gates compare
that SHA to the committed tree. A local case can execute dirty working-tree
content while still recording the older HEAD, so running it before the commit
creates a passing but stale verdict. If the tree changes after a case passes,
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
`command-ci` method, and that executor gates the pushed lane branch. Dash
branches otherwise stay local until merge. The recorded verdict names the CI
run URL and the exact head SHA it covered.

A project also declaring the merge-queue capability verifies
pull-request-first: the executor rebases the lane onto the base branch,
opens the landing pull request, and records that pull request's own entry
run as the verdict, so one suite covers the gate and queue entry both.
Expect the pull request to be visible from verification onward — step 7
enqueues that one rather than opening another. A rebase conflict stops
the gate before anything is published; resolve it on the lane and re-run,
which invalidates nothing because no evidence exists yet.

**Materialize the attached plan and run its cases before the transition.**
The `implementing` → `reviewing-implementation` preflight materializes every
plan attached at that stage into blocking case rows and only then evaluates
that stage's gates, so a transition attempted first creates the very
requirement that fails it. Attachment is independent of posture: a
project-default plan materializes even when no `verification` knob is
selected, and `done` refuses while any blocking requirement lacks a passing
run. Run this whenever `qa_plan_attachments` in `yoke items detail get ITEM
--json` names a plan for `reviewing-implementation`:

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

An empty listing means no plan is attached at that transition; do not invent
a substitute command or a hand-written run.

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
- `path_claims` — when selected, the lifecycle gate requires active concrete coverage now
  and compares the merged touched-file evidence with that coverage at done.
- `approval_on_done` — the final transition creates a project-owner decision
  request and stays blocked until an authorized owner approves it.
- `deployment` — after merge, run the selected/default item-bound project
  flow for the recorded merge identity and wait for status `succeeded`.

Move into the verification-close stage only when implementation checks pass
and every case materialized above carries a passing run — the transition
gates on those rows, so it is the last step of this section, never the step
that discovers them:

```text
yoke lifecycle transition ITEM --from implementing --to reviewing-implementation --reason "Implementation complete; verification passed"
```

### 6. Confirm the verified tree and merge

Immediately before merge, resolve the exact touched set again and replace the
survey with every actual file:

```text
yoke direct-workflow dash survey ITEM --path <actual-file> [--path <actual-file> ...] --json
```

If the result is blocked, do not merge. Coordinate, wait, tighten with claims,
or escalate. When clear, require a clean worktree whose HEAD is the tree named
by every passing SHA-bound verdict. Any intervening edit, commit, amend, or
rebase invalidates the old verdict: commit the final tree and rerun the affected
case. Do not merge by hand, force-push, bypass CI, or merge around a registered
claim.

### 7. Merge, record evidence, and finish

When deployment posture is selected, merge first without closing out, so the
item-bound deployment can run against the recorded merge identity:

```text
yoke merge item ITEM --skip-status --json
```

Start item-bound delivery for the returned `merge_sha`, run it through the
project executor, and wait for `succeeded`. Create requires the same-universe
owner-only local-postgres env (not the HTTPS product plane) — the same
`*-db-admin` connection execute uses:

```text
yoke --env <control-plane>-db-admin deployment-runs start-for-item ITEM \
  --release-lineage <merge-sha> --json
```

Otherwise merge and close out in one call. The operation resolves the touched
files from the branch itself, so no path list is needed:

```text
yoke merge item ITEM \
  --result "<what changed or was learned>" \
  --verification "<checks and evidence>" \
  --json
```

Add `--no-changes` for a genuine no-change result. When the merge is already
recorded and only the close-out remains — after a deployment run, or after
approval — record evidence and transition directly:

```text
yoke direct-workflow dash evidence ITEM \
  --result "<what changed or was learned>" \
  --verification "<checks and evidence>" \
  --commit-sha <sha> --merge-sha <sha> \
  --path <actual-file> [--path <actual-file> ...]
yoke lifecycle transition ITEM --from reviewing-implementation --to done --reason "Merged and evidence recorded"
```

When approval-on-done is selected, the terminal transition creates the owner
decision request without moving the item. Let an authorized owner resolve it,
then retry the transition. A successful standalone merge (or the terminal
transition it drives) may already release the item work claim and remove the
registered Dash worktree lane. Only release when a claim remains, or when
exiting before merge:

```text
yoke claims work release --item ITEM --reason "Dash completed"
```

Skip that call when merge or `done` already released the claim. Do not treat
an already-released claim as a close-out failure.

**Surface this session's guardrail denials.** After evidence is recorded,
report this episode's PreToolUse denials. Close-out reports; it does not block.
An empty result is silence: say nothing extra.

Read `session_id` from registered `sessions.identity`
(`yoke sessions identity`); do not invent it. `--session` filters
`events.session_id`. Do not pass `--session-id` — that flag overrides
caller identity. Then run registered `events.query.run`:

```text
yoke events query --session SESSION_ID --event-name HarnessToolCallDenied --current-episode --json
```

When `result.rows` is non-empty, print a short list of each row's
`check_id` and `command_snippet` from `envelope.context.detail` (parse
`envelope` when it is a JSON string). File a field-note for any denial
not already recorded, or state why none is warranted:

```text
yoke ouroboros field-note append --kind observation --evidence '...'
```

Do not correlate denials to field-notes in storage. Visibility is the
entire ask.
