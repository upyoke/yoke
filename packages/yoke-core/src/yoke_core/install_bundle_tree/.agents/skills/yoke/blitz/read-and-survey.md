# /yoke blitz steps 1–3 — read the document, survey, isolate

## 1. Read the item and execution document

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

## 2. Survey before activation

**Bounded discovery only.** Name candidate paths from the document's
affected areas — do not read them end to end here. Record the survey, then
move to step 3 before any deeper investigation or edit.

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

Apply File Budget and path claims as this matrix:

- both on: pair File Budget edit targets with complete claim coverage;
- budget off / claims on: derive claim paths from the execution document and
  survey;
- budget on / claims off: use the budget for sizing and conflict evidence
  without registering a claim;
- both off: the document and survey define execution scope without either
  artifact.

## 3. Claim, isolate, and activate atomically

Run this immediately after recording the survey above, before reading
further file contents or making any edit.

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


Next: [`integrate.md`](integrate.md).
