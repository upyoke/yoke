# Refine — Write, Verify, Advance

Typed writes only; never shell-transform a field:
```bash
yoke items structured-field append-addendum "$ITEM_REF" --field spec --heading "<addition-heading>" --source refine --stdin
```
Diff against the original before each write; re-read after. Any file
within the spec's scope that lacks a budget row: add the row (widen the
path claim if claims are on). Escalate only when scope changes. Write `worktree_plan` and
`shepherd_caveats` only in `generated_task_plan` scope.

Advance only on a full `pass`, then release:
```bash
yoke readiness check PREFIX-N
yoke lifecycle transition "$ITEM_REF" --from "$REFINE_ACTIVE_STATUS" --to "$REFINE_TARGET_STATUS" --reason "Refinement verified"
yoke claims work release --item "$ITEM_REF" --reason "completed"
```
`GATE_DB_CLAIM_PROSE_MISMATCH`: `yoke db-claim amend`, never scrub DDL.
Report via [shared handoff](../shared/stage-handoff.md).
