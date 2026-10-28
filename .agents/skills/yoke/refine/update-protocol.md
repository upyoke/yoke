# Refine — Write, Verify, Advance

Typed writes only; never shell-transform a field:
```bash
yoke items structured-field append-addendum "$ITEM_REF" --field spec --heading "<addition-heading>" --source refine --stdin
```
Diff against the original before each write; re-read after. One verified
missing owner in scope: add its budget row (widen if claims are on); more
than one, or changed scope, escalates. Write `worktree_plan` and
`shepherd_caveats` only in `generated_task_plan` scope.

Advance only on a full `pass`:
```bash
yoke readiness check PREFIX-N
yoke lifecycle transition "$ITEM_REF" --from "$REFINE_ACTIVE_STATUS" --to "$REFINE_TARGET_STATUS" --reason "Refinement verified"
```
`GATE_DB_CLAIM_PROSE_MISMATCH`: `yoke db-claim amend`, never scrub DDL.
Report via [shared handoff](../shared/stage-handoff.md).

If your launch instruction is a single-item mandate for this item, keep the
claim and run `/yoke {next_skill_id} ITEM` now: read and follow the next
bound skill in this turn. Otherwise show the next-skill line and release
the claim. A transition's `level_change` handoff takes precedence: release,
launch the returned successor, and end; follow `.yoke/docs/agents/levels.md`.
