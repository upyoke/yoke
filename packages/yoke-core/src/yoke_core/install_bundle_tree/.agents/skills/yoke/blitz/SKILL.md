---
name: blitz
description: "Execute a substantial document-led Blitz as integrated slices with continuous plan evidence."
argument-hint: "{PREFIX-N}"
---

# /yoke blitz {PREFIX-N}

Execute one refined Blitz directly from its single linked strategy
document. The document remains the live plan, progress log, handoff
surface, completion record, and parent-reconciliation record. The item
supplies identity, ownership, lifecycle, claims, worktrees, QA, and
delivery associations.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Registered operation authority

Use the registered function id as the operation authority. The `yoke`
commands taught later are adapters for these envelopes:

| Function id | Target and payload | CLI adapter |
|---|---|---|
| `items.detail.get` | Item target; empty payload | `yoke items detail get ITEM --json` |
| `workflows.item.get` | Item target; empty payload; centrally resolved effective policies | `yoke workflows item get ITEM --json` |
| `strategy.execution.get` | Blitz item target; empty payload | `yoke strategy execution get ITEM --json` |
| `strategy.doc.get` | Project target; `slug` | `yoke strategy doc get SLUG --project PROJECT --json` |
| `direct_workflow.blitz.survey` | Item target; `paths` plus optional `integration_target` | `yoke direct-workflow blitz survey ITEM --path PATH --json` |
| `lifecycle.transition.execute` | Item target; `source_status`, `target_status`, and `reason` | `yoke lifecycle transition ITEM --from STATUS --to STATUS --reason TEXT` |
| `strategy.coordination.append` | Project target; `slug`, `section`, and `entry` | `yoke strategy coordination append SLUG --section NAME --entry TEXT --project PROJECT` |
| `strategy.doc.replace` | Project target; `slug`, full `content`, `base_updated_at`, and shrink-guard posture | `yoke strategy doc replace SLUG --base-updated-at TS --content-file PATH --project PROJECT` |
| `strategy.claim.release` | Blitz item target; optional `reason` | `yoke strategy claim release ITEM --reason TEXT` |
| `claims.work.release` | Current item or claim target; `reason` | `yoke claims work release --item ITEM --reason TEXT` |

The survey has no item-claim precondition. Strategy reads, coordination
appends, document replacement, lifecycle transitions, and claim release
remain their own registered operation families; they are not hidden
Blitz-survey payloads. Execution-document linking belongs to `/yoke refine`
through `strategy.execution.link`, before this skill begins.

Worktree preparation and slice merging are each a
retained tool-shaped operation, because both act on the local checkout
rather than on control-plane state alone:

```text
yoke direct-workflow worktree prepare ITEM --workflow blitz
yoke merge item ITEM --skip-status
```

The first delegates to the local engine worktree preflight. The second is
the standalone-item merge boundary shared with Dash: it takes the merge
lock, lands the branch on the project base branch, stamps `merged_at`, and
publishes. Each command has no registered `direct_workflow.*` function id —
use them verbatim; do not invent function ids for them. Contract:
[`docs/archive/decisions/standalone-item-merge.md`](../../../../docs/archive/decisions/standalone-item-merge.md).

## Input and invariants

- `{PREFIX-N}` must resolve to a Blitz at `refined-idea`, `implementing`, or
  `reviewing-implementation`.
- Exactly one execution strategy document must already be linked by the
  refine flow. Do not copy it into an item body or generate child items.
- The item claim owns execution. The item-owned document claim owns plan
  revision. Other sessions may use only the append-only `Slice Log` and
  `Live Status` coordination surface.
- The default Blitz has File Budget and path claims off. It still obeys the
  universal 350-line authored-file limit, surveys before activation and every
  slice merge, judges each survey contact (proceed or yield), and runs every
  write in a registered isolated worktree.
- The main session owns slice boundaries, integration order, full
  verification, document completion, and parent reconciliation.
- Core invariants run on every action. A continuous delivery model never
  bypasses migration, capability, security, approval, or run-record rules.

## Execute

### 1. Read the item and execution document

Read both projections:

```text
yoke items detail get ITEM --json
yoke workflows item get ITEM --json
yoke strategy execution get ITEM --json
```

Require `workflow_id=blitz`, a single document slug, and no conflicting
active document claim. Read the full authoritative document with:

```text
yoke strategy doc get <SLUG> --project <PROJECT>
```

Extract the required outcomes, explicit slice boundaries, affected areas,
dependencies, delivery actions, verification, unresolved decisions, and
parent-strategy relationship. If the document cannot cold-start an
executor, stop for plan repair; do not fabricate scope.

Read effective `file_budget` and `path_claims` independently from
`workflows.item.get` at `result.effective_policies.file_budget` and
`result.effective_policies.path_claims`. `optional` is off; `required` and
`required_per_task` apply at their reported scopes. Never reconstruct these
values from raw policies or posture: the central projection owns historical
compatibility and allowed tightening. When File Budget is enabled, require
the execution document to carry an enumerated `## File Budget`; the document
remains the authority, so do not copy it into the item body. When disabled,
do not require that section. The universal 350-line check always applies.

### 2. Survey before activation

Translate the document's affected areas into likely file or directory
paths and record them:

```text
yoke direct-workflow blitz survey ITEM --path <path> [--path <path> ...] --json
```

Survey contacts are advisories: proceed when edits are independent, or
yield by authoring a dependency and dropping this claim. Coordinate
every collision in the execution document's append-only surfaces. Wait,
reorder slices, or enable and register path claims when the document
needs stronger serialization. A planned claim is not a stronger reason
to yield than an active one. Never omit a required area to obtain a
clear survey.

Apply the two axes as a four-state matrix:

- both on: pair File Budget edit targets with complete claim coverage;
- budget off / claims on: derive claim paths from the execution document and
  survey;
- budget on / claims off: use the budget for sizing and conflict evidence
  without registering a claim;
- both off: the document and survey define execution scope without either
  artifact.

### 3. Claim, isolate, and activate atomically

Prepare the item worktree:

```text
yoke direct-workflow worktree prepare ITEM --workflow blitz
```

Then activate:

```text
yoke lifecycle transition ITEM --from refined-idea --to implementing --reason "Blitz execution started"
```

This transition must acquire the item-owned document claim while the item
work claim and its registered worker worktree are held, after the live
`conflict_survey` gate passes. Confirm the claim in
`yoke strategy execution get ITEM --json`. If activation returns without
the document claim, stop; do not emulate the atomic contract with an
untracked document edit.

### 4. Build an integration map

The preparation call ensures the default worker lane through the active
authority, materializes every registered active lane on this machine, and
records each exact local path back through the guarded function-call surface.
Keep execution sequential in the default lane unless additional worker lanes
and an explicit integration lane have been registered through the universal
item-worktree surface:

```text
yoke item-worktrees create ITEM --lane-role worker --branch BRANCH
```

Repeat the same registered call with `--lane-role integration` for the one
explicit integration lane, then rerun the ordinary worktree preparation to
materialize every pathless registration over either HTTPS or machine-local
Postgres. Verify the authoritative set and its recorded paths with:

```text
yoke item-worktrees list ITEM --json
```

The item owns every registered lane; the main session holds the item work claim
while coordinating integration. Never parallelize by inventing an unregistered
branch or directory. Every worker brief must name:

- its outcome and exact file responsibility;
- its registered worktree;
- the focused verification it must run;
- the Slice Log entry it must append;
- the commit and integration expectation;
- that other workers exist and their edits must not be reverted.

The main session continues independent integration work while workers run.
It does not delegate the final plan reconciliation or full verification.

### 5. Execute and integrate one slice at a time

For each slice:

1. Re-read the relevant current document section and live coordination
   entries.
2. Make the smallest coherent change in its registered worktree.
3. Run focused verification with capture-first output — the individual
   failing tests, the changed module's paths, or the project's impacted
   selection (`yoke watch pytest --impacted main --bounded` here, which
   reports an unbounded selection instead of widening). When a slice has an
   attached Command case, that case run is the slice's one full execution:
   do not run the project's full sweep by hand and then hand the same tree to
   `yoke qa case run`, which re-runs the identical registered command. It
   streams live to stderr and names its raw capture file before starting.
4. Commit the slice with a descriptive current-function message.
5. Resolve the exact changed files and re-survey immediately before merge:

   ```text
   yoke direct-workflow blitz survey ITEM --path <actual-file> [--path <actual-file> ...] --json
   ```

6. Read each survey advisory and choose proceed or yield. Independent edits
   resolve at merge; order-dependent work authors a dependency, drops the
   claim, and re-offers. A planned claim is not a stronger reason to yield
   than an active one. Coordinate through `Slice Log`, reorder work, or
   register complete path claims before the next prepare. Do not silently
   resolve another owner's semantic changes.
7. When an integration lane is registered, it is the only merge source.
   Fold completed worker commits into it with `git merge` from inside the
   integration worktree; worker lanes keep building but never land on their
   own. Once the integration pull request is queued, do not commit or merge
   into that branch until it lands — a push removes it from the queue. Workers
   may continue in their own lanes during the wait; fold that work only after
   main fast-forwards from the completed landing.

   Merge the integrated slice through the standalone-item merge boundary.
   `--skip-status` keeps the item non-terminal — a Blitz closes out only when
   its execution document completes:

   ```text
   yoke merge item ITEM --skip-status --json
   ```

   The response carries the `merge_sha` for the checkpoint below. A
   queue-declared project keeps all registered lanes until the item is done.
   Only a project using the local merge engine needs to re-prepare the lane
   before the next slice, because that engine's cleanup deletes the landed
   branch. Run the delivery or migration action a slice itself requires; do
   not add one after every landing.
8. Append a cold-start-readable checkpoint:

   ```text
   yoke strategy coordination append <SLUG> --section "Slice Log" \
     --entry "<slice, merge SHA, verification, delivery, changed plan facts, next boundary>" \
     --project <PROJECT>
   ```

9. As the item-claim holder, revise the authoritative plan when the result
   changes scope, sequencing, decisions, or completion state. Use the
   registered strategy write surface and the current optimistic-concurrency
   token. An append is not a substitute for updating stale plan content.

Keep slices small and frequent. Do not hold completed code on a long-lived
branch merely to produce one terminal merge.

### 6. Review the whole execution

After the last slice is integrated:

- inspect all landed diffs and the current product path end to end;
- run the full relevant registered suite plus user-facing proof where
  applicable;
- confirm all governed migrations and delivery runs have evidence;
- remove obsolete paths the plan replaced;
- reconcile the execution document against every Slice Log checkpoint.

Transition into the once-per-item close:

```text
yoke lifecycle transition ITEM --from implementing --to reviewing-implementation --reason "All slices integrated; final reconciliation started"
```

### 7. Complete the document and close

Revise the linked strategy document so it explicitly records:

- what was completed;
- what changed from the starting plan;
- what remains, including an explicit statement when nothing remains;
- verification and delivery evidence with stable identities;
- how the parent strategy was reconciled, or that no parent exists.

Use this exact document-owned closeout shape so the completion gate can
distinguish terminal evidence from planning prose:

```markdown
## Blitz Completion

- Completed: <delivered outcomes>
- Changed: <departures from the starting plan, or none>
- Remaining: <open work, or nothing remains>
- Verification identities: <commands, receipts, runs, commits, or artifacts>
- Parent reconciliation: <parent update and revision, or no parent exists>
```

Append a final Slice Log entry naming the document revision and the final
verification result. Re-read `yoke strategy execution get ITEM --json` and
confirm the document claim still belongs to this item.

Transition through the `doc_completion` gate:

```text
yoke lifecycle transition ITEM --from reviewing-implementation --to done --reason "Execution document reconciled with passing evidence"
```

The terminal transition releases the item-owned document claim and every
registered Blitz worktree lane. Release the remaining session work claim:

```text
yoke claims work release --item ITEM --reason "Blitz completed"
```

If completion is blocked, keep the item at
`reviewing-implementation`, record the missing fact in `Live Status`, and
repair the document or evidence. Never weaken the completion gate.
