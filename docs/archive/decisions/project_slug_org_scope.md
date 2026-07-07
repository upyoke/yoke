# Apply the org-scoped project slug migration via the exception path

## Decision

Apply `runtime/api/domain/migrations/project_slug_org_scope.py` to the Yoke
stage and prod control-plane databases through the audit-fingerprint exception
path (`record_audit_fingerprint`), driven by
`runtime/api/tools/apply_self_migration.py`, rather than the item-bound governed
runner.

## Why the exception path

The migration replaces global `projects.slug` uniqueness with org-scoped
uniqueness (`UNIQUE(org_id, slug)`) and sets `projects.org_id NOT NULL`,
matching the org-scoped project addressing the code now expects. It is a
ticketless Yoke self-migration; the item-bound governed runner requires a
backlog item and work-claim this cleanup does not carry.

## Safety model

- **Rollback artifact.** Stage: a Postgres dump created before apply. Prod: a
  manual Aurora cluster snapshot taken and waited-available before apply. The
  reference is recorded in the audit row's `exception_reason`.
- **Guarded and idempotent.** `apply(conn)` requires the `projects` table,
  seeds the org shape when absent, asserts no duplicate `(org_id, slug)` pairs
  before creating the unique index, and uses `CREATE UNIQUE INDEX IF NOT
  EXISTS`; re-running is a no-op. `invariants(conn)` verifies the org-scoped
  index exists, the global slug constraint is gone, and `org_id` is `NOT NULL`.
- **Pre-checked.** Both control planes already have `org_id` populated on every
  `projects` row (verified by direct query), so the `NOT NULL` tightening cannot
  fail on existing data.

## Applied-everywhere and retirement

The module and its test are deleted only after both control planes record a
completed apply, per the delete-after-applied-everywhere rule.
