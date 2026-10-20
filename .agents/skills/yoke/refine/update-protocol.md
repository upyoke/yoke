# Refine — Write, Verify, Advance

Typed writes only; never shell-transform a field:
```bash
yoke items structured-field append-addendum "$ITEM_REF" --field spec --heading "<addition-heading>" --source refine --stdin
```
Diff against the original before each write; re-read after. One verified
missing owner in scope: add its budget row (widen if claims are on); more
than one, or changed scope, escalates.

Advance only on a full `pass`, then release:
```bash
yoke readiness check PREFIX-N
yoke lifecycle transition "$ITEM_REF" --from "$REFINE_ACTIVE_STATUS" --to "$REFINE_TARGET_STATUS" --reason "Refinement verified"
yoke claims work release --item "$ITEM_REF" --reason "completed"
```
`GATE_DB_CLAIM_PROSE_MISMATCH`: `yoke db-claim amend`, never scrub DDL.
Report via [shared handoff](../shared/stage-handoff.md).
