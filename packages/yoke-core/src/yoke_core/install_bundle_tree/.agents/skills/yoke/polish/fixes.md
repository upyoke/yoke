# Polish — Apply Finishing Fixes

Covers polish step 7: apply targeted finishing fixes to the worktree. Includes the DB-claim stop-and-amend gate when governed DB mutation is discovered.

**Context variables** (set by earlier phases): `ITEM_NUM`, `WORKTREE_PATH`, `WORKTREE_PATHS`.

---

## 7. Apply Finishing Fixes

Make targeted code and test changes within the relevant implementation worktree. For multi-worktree epics, apply each fix in the worktree that owns the changed files; do not copy a fix into sibling worktrees unless that sibling has the same verified gap. Fixes include:
- Closing AC gaps and end-to-end wiring gaps (ALL ACs, not just core implementation)
- Updating test files alongside implementation files (check for test-{module}.sh for every modified module)
- Deleting dead code, dead tests, dead config, dead migration scripts, and dead documentation
- Removing archaeological comments, compatibility shims, and legacy re-exports that serve nothing
- Replacing graceful migrations with hard cutovers when the old data no longer exists
- Updating docs, help text, and comments to describe the present as if the old way never existed
- Fixing blast-radius misses found via grep (callers, importers, configs, scripts that still reference old behavior)
- Running residue grep (`grep -r OLD_PATTERN .`) after any rename/removal to confirm zero remaining references
- Recording any prompt-surface or large-file size findings when they materially affect readability, dispatch quality, or future maintenance

Each fix should be verifiable — the fix should be testable or the deletion should be confirmable.

**DB-claim stop-and-amend.** If polish discovers governed DB mutation that the stored `db_mutation_profile` does not declare — schema changes, migration modules, bulk data, `migration_audit` writes — STOP and amend the claim before continuing. Inspect the current state, then route the correction through the unified `db-claim-amend` adapter (the CLI builds the `db_claim.amend` envelope internally):

```bash
yoke items get "YOK-${ITEM_NUM}" db_mutation_profile

yoke db-claim amend \
    --item "YOK-${ITEM_NUM}" \
    --reason "polish discovered governed DB mutation" \
    --payload -  # stream the unified DB claim payload on stdin
```

The handler demultiplexes the claim payload into the `db_mutation_profile` and `db_compatibility_attestation` columns atomically and writes a `DbClaimAmended` event; see [docs/db-reference.md](../../../../docs/db-reference.md) for the unified shape. The advance to `implemented` runs the prose-vs-claim gate (`GATE_DB_CLAIM_PROSE_MISMATCH`) plus the polish evidence gate, both of which would block the transition with a stale negative claim.

Function-call equivalent (for dispatch-surface callers — `db-claim-amend` builds this envelope internally):

```jsonc
{
  "function": "db_claim.amend",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "item", "item_id": $ITEM_NUM},
  "intent": "polish_db_mutation_discovered",
  "payload": {
    "reason": "polish discovered governed DB mutation",
    "claim": { "<unified DB claim payload>": "..." }
  }
}
```

**Fix what's broken, delete what's dead, flag what's big.** Polish fixes implementation gaps, deletes dead weight, and surfaces common-sense requirements the spec missed. If a missing requirement is straightforward and clearly implied by the ticket's purpose, fix it inline. If it would materially expand the ticket's scope (new subsystem, new user-facing feature, multi-file architectural change), flag it in the review report for the operator to decide. Do not refactor surrounding code or introduce new abstractions beyond what the item requires.
