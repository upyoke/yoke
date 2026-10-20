# Refine — Claim, Enter, Gather

```bash
yoke sessions touch --mode refine
yoke claims work acquire --item "$ITEM_REF" --reason refine_run
```
At the source stage with `item_artifact` scope, classify readiness first
([`readiness-repair.md`](readiness-repair.md)). Enter the active stage (skip on re-entry):
```bash
yoke lifecycle transition "$ITEM_REF" --from "$REFINE_SOURCE_STATUS" --to "$REFINE_ACTIVE_STATUS" --reason "Refinement started"
```
Read `spec`, `design_spec`, `technical_plan` (task-plan scope adds
`worktree_plan`, `shepherd_caveats`, tasks); `body` only if all are empty.
