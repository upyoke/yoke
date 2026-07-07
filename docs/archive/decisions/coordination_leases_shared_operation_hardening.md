---
title: coordination_leases_shared_operation_hardening — self-referential bootstrap exception
incident_type: durable-exception
owning-helper: runtime/api/domain/migrations/coordination_leases_shared_operation_hardening.py
exception-name: coordination_leases_shared_operation_hardening
retired-without-apply: false
---

# `coordination_leases_shared_operation_hardening` exception pathway

## What this records

The migration ships under `runtime/api/domain/migrations/` but does NOT run
through the governed two-unit (`rehearse` + `live-apply`) runner against the
authoritative DB. Instead, the module ships its own `apply` CLI that runs
the additive ALTER TABLEs, backfills `heartbeat_at`, verifies invariants,
and writes a completed `migration_audit` fingerprint via
`runtime.api.domain.migration_harness.record_audit_fingerprint`. The
governed-runner-shaped `apply(conn)` / `invariants(conn)` surface is
preserved so the rehearsal can still validate the module against the
worktree's validation DB.

## Why it is an exception rather than a governed-runner caller

The migration hardens the **lease primitive the governed runner itself
depends on**. The runner's contract is "acquire the
`LIVE_DB_MIGRATION:<model_name>` lease, apply the module, release the
lease" — but the lease acquisition path
(`runtime.api.domain.coordination_leases.acquire_lease`) unconditionally
reads and writes the new `heartbeat_at` and `actor_id` columns this module
is responsible for adding. Running the governed runner against an
authoritative DB whose `coordination_leases` table still has the old shape
raises `sqlite3.OperationalError: no such column: heartbeat_at` before the
apply even starts. The runner cannot bootstrap its own lock primitive.

Candidate workarounds considered and rejected:

1. **Add column-presence introspection to `acquire_lease`.** Doable but
   adds a hot-path schema check to every lease acquisition forever to
   handle a one-shot bootstrap window. The exception pathway is bounded;
   the introspection would be permanent.
2. **Split the migration into two modules — a "no-lease" pre-step that
   adds the columns and a governed module that does the rest.** The
   provenance columns on `migration_audit` are additive only, so there is
   no real second step; we would be inventing fake structure to satisfy
   the runner shape.

The chosen path keeps the change purely additive (no readers/writers
break across the merge boundary), records evidence through the same
`migration_audit` table the governed runner uses, and is bounded to the
one slice that hardens the lease primitive. Future shared-operation
consumers reusing the hardened primitive route through the governed
runner normally.

## Safety properties retained

- **Audit evidence.** `record_audit_fingerprint` writes a `migration_audit`
  row with `state='completed'`, `tables_declared`, `pre_row_counts`,
  `post_row_counts`, and `exception_reason`. The
  `HC-stranded-migration-module` doctor invariant treats this row as proof
  of apply, so the module-file deletion under AC-16 is keyed to the
  authoritative `state='completed'`.
- **Idempotent ALTER TABLEs.** `apply()` uses
  `runtime.api.domain.schema_common._add_column_if_not_exists` and a
  conditional backfill UPDATE; re-running the module against a partially-
  or fully-migrated DB is a no-op rather than an error.
- **Invariant gate.** `invariants(conn)` checks every added column is
  present and every row has a non-NULL `heartbeat_at`. The CLI raises if
  the invariants fail, so a malformed authoritative apply does not
  silently record `state='completed'`.

## Apply procedure

```bash
python3 -m runtime.api.domain.migrations.coordination_leases_shared_operation_hardening apply \
    --db-path "$(python3 -m runtime.api.domain.worktree paths db)"
```

Run once per install of the model's authoritative DB. After the
authoritative apply lands, delete the module file per AC-16; git history
preserves the record, and `HC-stranded-migration-module` enforces the
deletion via the completed audit row.
