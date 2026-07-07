# strategy_docs_per_project — exception-path authoritative apply

- date: 2026-06-11
- pathway: `record_audit_fingerprint` exception (operator-mandated, ceremony-free)
- caller: `runtime/api/tools/apply_strategy_docs_cutover.py` (one-shot; deleted with the module at retire time)

## What applied

The `strategy_docs_per_project` cutover module against the prod
authoritative Postgres: `strategy_docs.project_id` added (NOT NULL, FK
`projects.id`), every pre-existing row backfilled onto the Yoke
project (slug-resolved), global slug uniqueness replaced by
`(project_id, slug)`, and the `project_structure` mappings glob
re-pointed `strategy/**` → `.yoke/strategy/**`.

## Why the exception pathway

The item-bound governed runner (`migration_apply rehearse/live-apply`)
requires full ticket wiring; the operator explicitly overrode that
ceremony for this cutover ("do the governed db migration but no other
ceremony", 2026-06-11). The exception pathway preserves the contract's
substance:

- **Rehearsal evidence:** `test_strategy_docs_per_project_migration.py`
  ran the module's `apply()` against the legacy shape plus `invariants()`
  on a validation Postgres the same day (green, including idempotent
  re-apply and fresh-shape no-op).
- **Rollback:** a manual RDS cluster snapshot of `prod-db-cluster`
  precedes the apply, and `record_audit_fingerprint` creates a Postgres
  rollback dump (`backup_reason="strategy-per-project-cutover"`) before
  the audit row lands.
- **Discoverability:** the completed apply is a `migration_audit` row
  (`exception_reason` populated), satisfying the retire gate's
  applied-everywhere evidence.

A declared `db_mutation_profile` (hard_cutover, pre_merge_breaking,
founder_cutover posture) was recorded on the cutover ticket at intake
for audit provenance; the ticket carries no other lifecycle role.
