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
yoke direct-workflow dash survey ITEM --no-changes --json  # genuine no-change only
```

A reported overlap remains advisory. Read the overlapping path, holding item,
and sanctioned routes. Proceed when the edits are independent. When they are
order-dependent, wait for the holding work to land (merge receipt, merged_at,
or git ancestry — not status) and re-run the survey; when
they remain unresolved, release the work claim and present the path, holder, and
evidence to the operator. The re-survey itself remains mandatory, but a contact
does not by itself prevent the commit or case. Commit the coherent change in the
worktree. Both the local
`worktree_run` runner and the remote `ci_run` runner record
`verification_tree.head_sha`; the merge and done gates compare that SHA to the
committed tree. A local case can execute dirty working-tree content while still
recording the older HEAD, so running it before the commit creates a passing but
stale verdict. If the tree changes after a case passes, re-survey, commit, and
rerun every affected SHA-bound case.

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
effective plan attached at that stage into blocking case rows and only then
evaluates that stage's gates. Project defaults are effective only for workflow
QA policies that declare project defaults. Dash's
`optional_item_attachment` policy ignores them and has no definition-owned
`qa_verification` done gate; an item-specific verification posture still adds
and enforces its own plan. Run this whenever `qa_plan_attachments` in `yoke
items detail get ITEM --json` names a plan for `reviewing-implementation`:

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
yoke direct-workflow dash survey ITEM --no-changes --json  # genuine no-change only
```

Read any reported contacts as advisories here too; a recorded overlap does not
itself prevent merge. Proceed when the edits are independent. For
order-dependent work, wait for the holding work to land (merge receipt,
merged_at, or git ancestry — not status) and re-run the survey;
for an unresolved contact, release the work claim and present the path, holder,
and evidence to the operator. Then require a clean worktree whose HEAD is the
tree named by every passing SHA-bound verdict. Any intervening edit, commit,
amend, or rebase invalidates the old verdict: commit the final tree and rerun the
affected case. Do not merge by hand, force-push, bypass CI, or merge around a
registered claim.

### 7. Merge, record evidence, and finish

Merge-queue projects use a two-call handoff by default. The first call opens /
rebases / arms the pull request, returns `landing_pending=true`, and leaves the
claim and item non-terminal; end this execution pass. After the control-plane
message says landing is complete, re-enter the same command to close out.
A re-entry while `landing_pending=true` publishes any new local lane commits
before the queue is (re)armed. `ok:true` means the reported `commit_sha` is
the head origin holds and the queue will build. If that push cannot happen,
the command refuses with the remote head, the unpublished local commits, and
the exact `git push --force-with-lease` recovery — it never reports the new
SHA while origin still holds the old one.
Codex and Cursor may add `--wait` to keep both phases inline when their process
is safe for the full wait. Claude must never pass `--wait`. `--wait` returns
immediately with a terminal failure when the pull request's required checks
have already concluded red and nothing is in flight for that head sha; the
poll budget applies only while checks or the train are genuinely pending.

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

Otherwise issue the merge-and-close-out command. Non-queue projects and an
explicit `--wait` finish inline; the default queue route follows the handoff
above. The operation resolves the touched files from the branch itself, so no
path list is needed. Dash close-out is
evidence-gated on this same command — pass `--result` and `--verification`
even when the merge queue already landed the branch. Do not substitute
`yoke lifecycle transition --to done`; that path cannot restore the work
claim the landing handoff retains.

```text
yoke merge item ITEM \
  --result "<what changed or was learned>" \
  --verification "<checks and evidence>" \
  --json
```

Add `--no-changes` for a genuine no-change result. When the merge is already
recorded and only the close-out remains — after a deployment run, after
approval, or after a queue landing that has not reached `done` — re-run the
same merge command with `--result` and `--verification`. It restores the
work claim close-out needs and records evidence if the merge identity is
not yet on the item. Do not hand-run `lifecycle.transition --to done` for
Dash close-out.

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

When `result.elided_prior_episode_rows` is present, this session crossed
an episode boundary mid-Dash — a sleep, a reload, a brief disconnect —
and that many denials sit in the previous episode. Re-run the same query
without `--current-episode` and report the whole session's denials. An
empty `rows` beside a non-zero count is not a clean run.

When `result.rows` is non-empty, print a short list of each row's
`check_id` and `command_snippet` from `envelope.context.detail` (parse
`envelope` when it is a JSON string). File a field-note for any denial
not already recorded, or state why none is warranted:

```text
yoke ouroboros field-note append --kind observation --evidence '...'
```

Do not correlate denials to field-notes in storage. Visibility is the
entire ask.

### Laneless and evidence-only close-out

Two closes record no merge SHA, and both are first-class rather than a
bypass. A genuine no-changes finding edited nothing:

```text
yoke direct-workflow dash evidence ITEM --result "<account>" \
  --verification "<what you observed>" --no-changes --json
```

An item whose pinned workflow delivers merge-free — `worktrees=none`,
`delivery=merge_free`, the floor Task shape — did change things, and
names them as the observed changes:

```text
yoke direct-workflow dash evidence ITEM --result "<account>" \
  --verification "<what you observed>" --path notes/readme.txt --json
```

Do not reach for `--no-changes` to skip the SHAs on a laneless item that
did change files: the floor rung comes from the item's own delivery
policy, so the SHAs are already optional and `--no-changes` would record
the wrong fact. A merging workflow that omits its SHAs is refused, and
the refusal names both routes.

Task items have no `reviewing-implementation` stage. Close
`implementing` → `done` once the attestation is recorded:

```text
yoke lifecycle transition ITEM --from implementing --to done \
  --reason "Floor attestation recorded"
```

Outward-action approval gating is a future seam; do not invent one here.
