# Additive control-plane schema catch-up via the governed exception path

## What

A one-time, out-of-band additive schema convergence applied directly to the
`stage` and `prod` control-plane universes through the `record_audit_fingerprint`
governed exception pathway, adding surfaces that a plain deploy never propagated:

- `projects.github_sync_mode` (`TEXT DEFAULT NULL`)
- `organizations.auto_join_domain` (`TEXT`)
- the three external sign-in identity tables — `actor_external_identities`,
  `actor_invites`, `web_sessions` — and their indexes.

The DDL is the migration module `external_signin_and_sync_mode_schema` reused via
the one-shot tool `runtime/api/tools/converge_signin_sync_mode_schema.py`; both
are transient and removed after the apply.

## Why an out-of-band apply

These surfaces were added to the schema-init chain after the control-plane
universe's last full init. Boot's `ensure_core_schema` historically ran only
`create_core_tables` (a no-op on existing tables), so no deploy ever added them —
the live universe ran current code while missing five schema surfaces. The
durable fix is the boot-time full schema convergence (`converge_core_schema`,
landed on main), which propagates additive schema on every future deploy. This
record covers the **one-time catch-up** onto the already-born universes, applied
before the boot-converge code deploys, so the flip that depends on
`github_sync_mode` (pointing the project at the public repo with sync off) is
unblocked immediately rather than waiting on a deploy.

## Why the exception path rather than the governed runner

The change is purely additive and idempotent (`ADD COLUMN IF NOT EXISTS`,
`CREATE TABLE IF NOT EXISTS`), reuses the canonical DDL owners, and is covered by
regression tests. The governed runner requires a backlog ticket to carry the
`db_mutation_profile`, which the active Fair Source push explicitly runs without.
The `record_audit_fingerprint` exception pathway is the sanctioned alternative:
it records a discoverable `migration_audit` row and takes its own `pg_dump`
rollback backup, without minting a ticket.

## Safety argument

- **Compatibility:** strictly additive; no reader or writer is broken across the
  change. Nullable / `NOT NULL DEFAULT` columns self-populate; the new tables are
  net-new.
- **Idempotent:** safe to re-run and safe alongside the boot-time convergence
  that also owns this DDL.
- **Backups:** an RDS cluster snapshot of `prod-db-cluster` is taken and
  confirmed `available` before the prod apply, and `record_audit_fingerprint`
  additionally creates a `pg_dump` rollback artifact recorded on the audit row.
- **Canary:** applied to `stage` (`yoke-stage-aurora`) first and verified before
  `prod`.
- **Verification:** the module's `invariants` assert all five surfaces exist
  after apply; the tool prints pre/post state for both environments.

## Rollback

Additive surfaces are trivially reversible (`DROP` the three tables, `DROP`
the two columns) and no data is rewritten, so a rollback would be a manual
additive-reverse. The RDS snapshot and the `pg_dump` artifact provide full
point-in-time recovery if ever needed.
