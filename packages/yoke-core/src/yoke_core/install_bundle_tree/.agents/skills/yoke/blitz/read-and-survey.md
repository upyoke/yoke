# Blitz — read, survey, isolate

## 1. Read authority

```sh
yoke items detail get ITEM --include '' --json
yoke workflows item get ITEM --json
yoke strategy execution get ITEM --json
yoke strategy doc get <SLUG> --project <PROJECT>
```

Require `workflow_id=blitz`, one linked slug and no conflicting active
document claim. Extract outcomes, explicit slices, areas, dependencies,
delivery, verification, unresolved decisions and parent relationship.
Insufficient cold-start instructions require plan repair before execution.

Read `result.effective_policies.file_budget` and `.path_claims` independently
from `workflows.item.get`: `optional` is off; `required`/`required_per_task`
apply at returned scopes. The central projection owns compatibility/tightening.
Enabled File Budget requires an enumerated `## File Budget` in the execution
document, without copying it into the item; off requires none. Always 350 lines.

## 2. Bounded survey before activation

Name candidate paths from document areas, without end-to-end file reads.
Include every required area, then record:

```sh
yoke direct-workflow blitz survey ITEM --path <path> [--path <path> ...] --json
```

Contacts are advisory: proceed for independent edits; order-dependent work
authors a dependency, drops the claim and yields. Planned claims are no stronger
than active claims. Coordinate collisions in append-only document surfaces;
wait, reorder or enable/register complete claims for stronger serialization.

| Budget | Claims | Scope evidence |
|---|---|---|
| on | on | Budget targets plus complete claim coverage |
| off | on | Document/survey-derived claim paths |
| on | off | Budget sizing/conflicts, without claim registration |
| off | off | Document and survey, without either artifact |

## 3. Prepare immediately; activate atomically

Before deeper investigation or edits:

```sh
yoke direct-workflow worktree prepare ITEM --workflow blitz
```

The last JSON envelope reports success/refusal. Read `lane_orientation`
for declared `package_roots`, `test_roots` and `focused_test_command`.

For activation, refresh `yoke workflows item get ITEM --json` and its pin
with `yoke workflows version get <workflow-id> <workflow-version> --json`.
`LIVE_STAGE` is status; `NEXT_STAGE` is the unique forward edge in
`definition.transitions` from that status, ordered by `definition.stages`.
Confirm the active half-open `definition.skill_bindings` interval owns Blitz.
Absent/ambiguous edge: `workflow_next_stage_ambiguous`; workflow owner repairs
or selects a declared route. Resumed active lanes skip activation.

```sh
yoke lifecycle transition ITEM --from <live-stage> --to <next-stage> --reason "Blitz execution started"
```

Activation atomically acquires the item-owned document claim while holding
the work claim/registered worker lane, after `conflict_survey`. Confirm through
`yoke strategy execution get ITEM --json`. A missing document claim stops
execution; repair the atomic contract before editing.

Next: [integrate.md](integrate.md).
