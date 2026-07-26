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

## Input and invariants

- `{PREFIX-N}` must resolve to a Blitz at `refined-idea`, `implementing`, or
  `reviewing-implementation`.
- Exactly one execution strategy document must already be linked by the
  refine flow. Do not copy it into an item body or generate child items.
- The item claim owns execution. The item-owned document claim owns plan
  revision. Other sessions may use only the append-only `Slice Log` and
  `Live Status` coordination surface.
- The default Blitz is claim-less at path level. It still surveys before
  activation and before every slice merge, yields to registered claims,
  and runs every write in a registered isolated worktree.
- The main session owns slice boundaries, integration order, full
  verification, document completion, and parent reconciliation.
- Core invariants run on every action. A continuous delivery model never
  bypasses migration, capability, security, approval, or run-record rules.

## Execute

### 1. Read the item and execution document

Read both projections:

```text
yoke items detail get ITEM --json
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

### 2. Survey before activation

Translate the document's affected areas into likely file or directory
paths and record them:

```text
yoke direct-workflow blitz survey ITEM --path <path> [--path <path> ...] --json
```

Registered claims always win. Coordinate every collision in the execution
document's append-only surfaces. Wait, reorder slices, or enable and
register path claims when the document needs stronger serialization.
Never omit a required area to obtain a clear survey.

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
work claim is held and must pass the live `conflict_survey` gate. Confirm
the claim in `yoke strategy execution get ITEM --json`. If activation
returns without the document claim, stop; do not emulate the atomic
contract with an untracked document edit.

### 4. Build an integration map

Use one integration lane owned by this session. Create additional worker
lanes only for slices with explicit non-overlapping ownership. Every worker
brief must name:

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
3. Run focused verification with capture-first output.
4. Commit the slice with a descriptive current-function message.
5. Resolve the exact changed files and re-survey immediately before merge:

   ```text
   yoke direct-workflow blitz survey ITEM --path <actual-file> [--path <actual-file> ...] --json
   ```

6. Yield on contact with registered claims. Coordinate through `Slice Log`,
   reorder work, or tighten the Blitz with complete path claims. Do not
   silently resolve another owner's semantic changes.
7. Merge the slice through the project's protected merge path and run any
   delivery/migration action that the slice itself requires.
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

Append a final Slice Log entry naming the document revision and the final
verification result. Re-read `yoke strategy execution get ITEM --json` and
confirm the document claim still belongs to this item.

Transition through the `doc_completion` gate:

```text
yoke lifecycle transition ITEM --from reviewing-implementation --to done --reason "Execution document reconciled with passing evidence"
```

Release the document claim and item work claim through their registered
surfaces:

```text
yoke strategy claim release ITEM --reason "Blitz completed"
yoke claims work release --item ITEM --reason "Blitz completed"
```

If completion is blocked, keep the item at
`reviewing-implementation`, record the missing fact in `Live Status`, and
repair the document or evidence. Never weaken the completion gate.
