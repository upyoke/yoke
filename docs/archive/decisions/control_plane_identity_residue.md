# Apply the control-plane identity residue migration via the exception path

## Decision

Apply `runtime/api/domain/migrations/control_plane_identity_residue.py` to the
Yoke stage and prod control-plane databases through the audit-fingerprint
exception path (`record_audit_fingerprint`), driven by the operator tool
`runtime/api/tools/apply_self_migration.py`, rather than the item-bound governed
runner.

## Why the exception path

The migration is a ticketless Yoke self-migration: it erases old-product-name
identity residue left on a control-plane database after the Sunday → Yoke
rename. The item-bound governed runner requires a backlog item with a
`db_mutation_profile` and a work-claim; this cleanup is not carried by a ticket.
This mirrors the original rename cutover, which recorded `migration_audit`
`yoke_rename_db_cutover` (#556) as "a verified transactional cutover with Aurora
snapshot backup" through the same exception path.

## Safety model

- **Rollback artifact.** Stage: a Postgres dump created by
  `create_exception_backup` before apply. Prod: a manual Aurora cluster snapshot
  taken and waited-available before apply. The artifact reference is recorded in
  the audit row's `exception_reason`.
- **Transactional apply.** `apply(conn)` runs in one transaction and calls
  `invariants(conn)` at the end — a generic zero-residue sweep over every
  text-typed column of every base table except the `events` and
  `ouroboros_entries` history ledgers — so any missed residue aborts the whole
  apply.
- **Idempotent.** Re-running finds no residue and changes nothing; the audit row
  makes the apply discoverable to `HC-oneshot-migration-coverage`.

## Applied-everywhere and retirement

Prod was already residue-free before this migration (verified by direct query),
so the prod apply is a no-op that records the clean-state audit row; stage
carried the residue and is normalized. The migration module and its test are
deleted only after both control planes record a completed apply, per the
delete-after-applied-everywhere rule.
