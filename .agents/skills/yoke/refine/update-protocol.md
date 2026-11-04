# Refine — Write, Verify, Advance

Typed writes only; never shell-transform a field:
```bash
yoke items structured-field append-addendum "$ITEM_REF" --field spec --heading "<addition-heading>" --source refine --stdin
```
Diff against the original before each write; re-read after. Any file
within the spec's scope that lacks a budget row: add the row (widen the
path claim if claims are on). Escalate only when scope changes. Write `worktree_plan` and
`shepherd_caveats` only in `generated_task_plan` scope.

Advance only on a full `pass`:
```bash
yoke readiness check PREFIX-N
yoke lifecycle transition "$ITEM_REF" --from "$REFINE_ACTIVE_STATUS" --to "$REFINE_TARGET_STATUS" --reason "Refinement verified"
```
`GATE_NEW_MIGRATIONS_NEED_DB_CLAIM`: declare the listed lane-only migration
entries with `yoke db-claim amend`. Spec wording does not trigger this gate.
Release and boot refuse live references to the retired gate; migrate affected
items on the running build with `yoke workflows item migrate PREFIX-N`.
Report via [shared handoff](../shared/stage-handoff.md).

If your launch instruction is a single-item mandate for this item, keep the
claim and run `/yoke {next_skill_id} ITEM` now: read and follow the next
bound skill in this turn. Otherwise show the next-skill line and release
the claim. A transition's `level_change` handoff takes precedence: release,
launch the returned successor, and end; follow `.yoke/docs/agents/levels.md`.
