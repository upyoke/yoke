# Engineer — DB Schema Changes Migration Protocol

Reference material for the Engineer agent. Read it before any task that modifies the database schema (ALTER TABLE, CREATE TABLE, DROP TABLE, ADD COLUMN, etc.).

**Schema discovery first:** locate the project's fresh-schema creator, additive-schema converger, column helper, and schema expectation registry. In Yoke-like projects these are commonly named `create_core_tables`, `apply_additive_schema`, `_add_column_if_not_exists`, and `_EXPECTED_SCHEMA_STR`; search the active source tree for the names rather than assuming any repository layout.

**Boot-propagation doctrine:** additive schema (net-new tables, columns, or indexes) should use the project's idempotent boot-time convergence path when one exists. Data-transforming migrations (backfills, drops, column removals, table rewrites) use the governed migration path. Never assume that a source path from another project owns either behavior.

## Routing: additive schema vs data-transforming migration

**First classify the change.** Pure-additive schema (net-new `CREATE TABLE`, `ADD COLUMN`, `CREATE INDEX`) follows the project's verified idempotent convergence mechanism and does not need live DDL when that mechanism applies. Data-transforming migrations (backfills, drops, column removals, table rewrites) are the ONLY class that uses the governed path below.

## For a data-transforming migration

You author the change; you do not apply it. A server brings its own database
up to the code it runs before it serves, so the apply happens on the boot
converge after your work merges and deploys.

1. **Add an entry to the ordered history.** Name it `NNNN_slug.py` in the
   model's migrations package, next sequence number. It exposes `apply(conn)`
   and optionally `invariants(conn)`.
2. **The body must be safe to re-run and must NOT commit.** The applier
   commits your entry together with its ledger row, which is what makes
   "applied but unrecorded" impossible; committing inside `apply()` splits
   that transaction and gives the guarantee back. Guard every statement
   (`IF EXISTS` / `IF NOT EXISTS`, or an explicit state check) — a database
   restored from a pre-ledger archive replays its history.
3. **Never delete it afterwards.** Entries are permanent. A module that is
   gone cannot be applied by a universe that never received it.
4. **Rehearse before merging:** `yoke migration rehearse PREFIX-N` from a
   local-Postgres or matching db-admin connection. That runs
   the entry against the model's validation surface and records the receipt
   the evidence gate reads. It also takes the migration-territory lease and
   holds it, so a second work item cannot start a migration on the same model
   while yours is in flight.
5. **Treat "already at or beyond my target" as finished, not as an error.**
   A permanent entry outlives the shape it was written against. An entry that
   pins a version constant and rejects anything newer will start failing boots
   the moment the schema moves on — it has not become wrong, it has become
   done.

## For new columns (ADD COLUMN)

A pure-additive column needs no manual live `ALTER TABLE` or governed migration apply when the project's boot convergence is verified to handle it. Update every project-specific surface that defines the schema:

1. **Fresh-schema creator** — add the column to the table's creation statement in the function located during discovery (often `create_core_tables`).
2. **Additive convergence step** — add the idempotent column declaration to the additive converger (often `apply_additive_schema`) through the project's column helper (often `_add_column_if_not_exists`). Do not put an additive change in a legacy-data or one-shot migration wrapper. The new column must be self-sufficient on add — nullable, or `NOT NULL DEFAULT` where the database can populate existing rows.
3. **Schema expectation registry** — extend the expected table shape in the project's drift check (often `_EXPECTED_SCHEMA_STR`).
4. **Project documentation** — update the schema reference and the table-specific documentation that the project actually ships.
5. **Domain field projections** — update any field lists, serializers, or domain wrappers that enumerate the table's columns.

## For destructive operations (DROP TABLE, table rebuild, column removal)

Write a history entry with row-count validation and rehearsal support, then
rehearse it. Never use raw ALTER TABLE for destructive live operations. These
are data-transforming migrations, not additive schema, so they always take the
history path above — they do not self-propagate on boot.

## After migration

Run doctor through the canonical watcher wrapper to verify the schema matches expectations (per AGENTS.md `## Command Output — Hard Rule`):
```bash
yoke watch doctor -- --only HC-schema-drift
```

## Checklist summary

- [ ] Change classified: additive schema (self-propagates on boot) vs data-transforming migration (governed path)
- [ ] (Data-transforming migrations only) Entry added to the ordered history as `NNNN_slug.py`, guarded, safe to re-run, and not committing inside `apply()`
- [ ] (Data-transforming migrations only) Rehearsal run and its receipt recorded; the entry is NOT deleted afterwards
- [ ] (Additive schema) Additive converger updated so the column reaches existing environments on deploy or boot
- [ ] Fresh-schema creator updated
- [ ] Idempotent column helper used in the additive converger, not a legacy-data or one-shot migration wrapper
- [ ] Schema expectation registry updated
- [ ] Project schema documentation updated
- [ ] Relevant domain field projections updated
- [ ] Dedicated history entry with row-count verification for destructive operations
- [ ] Doctor passes after migration (`yoke watch doctor -- --only HC-schema-drift`)
