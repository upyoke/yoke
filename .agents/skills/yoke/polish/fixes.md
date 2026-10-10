# Polish — Apply Finishing Fixes

## 7. Fix within the item

Edit each fix in its owning registered lane. Copy to a sibling only after
verifying that sibling has the same gap. Close all AC/end-to-end gaps with
test co-modification, helper dependencies, present-tense docs/help/comments,
zero rename/removal residue and prompt/readability fixes. Delete verified dead
code/tests/config/docs and unused compatibility, **retain permanent ordered
migration history**. Each edit or deletion needs verifiable evidence.

**DB-claim stop-and-amend:** undeclared schema changes, migration modules,
bulk data or migration-audit writes STOP work before continuing. Inspect and
amend through `db_claim.amend`:
```bash
yoke items get "$ITEM_REF" db_mutation_profile
yoke db-claim amend "$ITEM_REF" --reason "polish discovered governed DB mutation" --stdin
```

Supply the unified claim on stdin; read the
[DB reference](../../../../.yoke/docs/reference/db-reference.md) and database
operation rules for its shape. The handler atomically updates
`db_mutation_profile` and `db_compatibility_attestation` and records a
best-effort `DbClaimAmended` event. Inspect the pinned target's actual gates:
a stale negative claim blocks `GATE_DB_CLAIM_PROSE_MISMATCH` and the polish
evidence gate wherever declared.

Fix straightforward requirements clearly implied by the item's purpose inline.
Flag material expansion—a new subsystem, user feature or multi-file architecture
change—for operator decision. Do not refactor surrounding code or introduce
abstractions beyond the item. Then [verify and commit](verify-and-commit.md).
