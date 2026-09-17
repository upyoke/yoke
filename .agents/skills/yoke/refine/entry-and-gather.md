# /yoke refine steps 1–2 — parse, claim, gather

## 1. Parse And Lookup

Read and follow [`workflow-context.md`](workflow-context.md). It resolves the
exact pin and exports `ITEM_*`, `REFINE_SOURCE_STATUS`,
`REFINE_ACTIVE_STATUS`, `REFINE_TARGET_STATUS`, and
`REFINE_ARTIFACT_SCOPE`. Do not continue unless its skill guard passes.

## 1b. Claim and Set Entry Status

The workflow-context interpreter already proved the current stage belongs to
exactly one pinned `refine` binding:

- At `REFINE_SOURCE_STATUS`, transition to `REFINE_ACTIVE_STATUS` before work.
- At `REFINE_ACTIVE_STATUS`, proceed without a status write (re-entry).
- Any other stage was rejected in step 1.

Register the work claim BEFORE the status transition (claim-before-status ordering). The session stamp uses the registered session wrapper. This prevents the scheduler from offering the same item while refine is actively working on it, and ensures the subsequent status mutation passes claim verification:

```bash
# Reuse ITEM_REF and ITEM_NUM from step 1. The items.get dispatcher already
# resolved prefixed, zero-padded, and project-local bare-number input.
# Session touch + claim
yoke sessions touch --mode refine
yoke claims work acquire \
 --item "$ITEM_REF"
```

For `REFINE_ARTIFACT_SCOPE=item_artifact`, run the internal pre-handoff
readiness gate before the entry status mutation. The effective flags resolved
from the immutable pin control its checks: File Budget validation runs only
when `ITEM_FILE_BUDGET_POLICY` is non-`optional`, path-claim required checks run only when
`ITEM_PATH_CLAIMS_POLICY` is non-`optional`, and coverage parity runs only when both are
true. Read and follow
[`readiness-repair.md`](readiness-repair.md) for the full classifier
table (`pass` / `pure_stale_count` auto-fix / `FILE_BUDGET_NOT_IN_CLAIM`
auto-widen / `mixed_stale_count` continuation / `unrecoverable`
terminal block), the routing rationale, exact registered commands, claim
release behavior, and `/yoke do` chain-step contract. Run it only when
`REFINE_ARTIFACT_SCOPE=item_artifact` and
`ITEM_STATUS=REFINE_SOURCE_STATUS`.

Then set the entry status, when needed, via the
`lifecycle.transition.execute`
function call (envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)):

- At `REFINE_SOURCE_STATUS`, use `payload = {target_status:
  REFINE_ACTIVE_STATUS, source_status: REFINE_SOURCE_STATUS}`.
- At `REFINE_ACTIVE_STATUS`, do not emit a no-op transition.

## 2. Gather Artifacts

Read all available structured fields. Empty fields are normal; refinement should still inspect them and decide whether a light structural improvement is warranted.

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
# Reuse ITEM_REF and ITEM_NUM from step 1.
BODY=$(yoke items get "$ITEM_REF" body 2>/dev/null) || true
SPEC=$(yoke items get "$ITEM_REF" spec 2>/dev/null) || true
DESIGN_SPEC=$(yoke items get "$ITEM_REF" design_spec 2>/dev/null) || true
TECHNICAL_PLAN=$(yoke items get "$ITEM_REF" technical_plan 2>/dev/null) || true
WORKTREE_PLAN=$(yoke items get "$ITEM_REF" worktree_plan 2>/dev/null) || true
SHEPHERD_CAVEATS=$(yoke items get "$ITEM_REF" shepherd_caveats 2>/dev/null) || true
```

When `REFINE_ARTIFACT_SCOPE=generated_task_plan`, also inspect the persisted
child decomposition selected by `ITEM_GENERATED_CHILDREN=epic_tasks`:

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
EPIC_TASKS=$(yoke epic-tasks list --epic "$ITEM_NUM" 2>/dev/null) || true
```

If all fields are empty or trivial, emit:
> **Advisory:** PREFIX-N has minimal content. Consider populating the body first or running `/yoke shepherd PREFIX-N` before refining.

Proceed anyway — refinement can still add structure to sparse items.


Next: [`survey-and-focus.md`](survey-and-focus.md).
