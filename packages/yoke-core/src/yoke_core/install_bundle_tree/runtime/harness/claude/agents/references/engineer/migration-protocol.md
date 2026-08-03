# Engineer — DB Schema Changes Migration Protocol

Reference material for the Engineer agent. Read it before any task that modifies the database schema (ALTER TABLE, CREATE TABLE, DROP TABLE, ADD COLUMN, etc.).

**Schema discovery first:** locate the project's fresh-schema creator, additive-schema converger, column helper, and schema expectation registry. In Yoke-like projects these are commonly named `create_core_tables`, `apply_additive_schema`, `_add_column_if_not_exists`, and `_EXPECTED_SCHEMA_STR`; search the active source tree for the names rather than assuming any repository layout.

**Boot-propagation doctrine:** additive schema (net-new tables, columns, or indexes) should use the project's idempotent boot-time convergence path when one exists. Data-transforming migrations (backfills, drops, column removals, table rewrites) use the governed migration path. Never assume that a source path from another project owns either behavior.

## Routing: additive schema vs data-transforming migration

**First classify the change.** Pure-additive schema (net-new `CREATE TABLE`, `ADD COLUMN`, `CREATE INDEX`) follows the project's verified idempotent convergence mechanism and does not need live DDL when that mechanism applies. Data-transforming migrations (backfills, drops, column removals, table rewrites) are the ONLY class that uses the governed path below.

## Before a data-transforming migration

1. **Use the governed migration-apply path for live DDL.** The intended
   agent-facing wrapper is pending; until it exists, do not invent a raw
   module recipe in task prose. Dispatch context must name the sanctioned
   migration rehearse/live-apply surface explicitly before an Engineer runs
   live DDL.
2. Verify the live-apply audit row records a non-empty `backup_path` and that
   the referenced Postgres rollback dump exists.

## For new columns (ADD COLUMN)

A pure-additive column needs no manual live `ALTER TABLE` or governed migration apply when the project's boot convergence is verified to handle it. Update every project-specific surface that defines the schema:

1. **Fresh-schema creator** — add the column to the table's creation statement in the function located during discovery (often `create_core_tables`).
2. **Additive convergence step** — add the idempotent column declaration to the additive converger (often `apply_additive_schema`) through the project's column helper (often `_add_column_if_not_exists`). Do not put an additive change in a legacy-data or one-shot migration wrapper. The new column must be self-sufficient on add — nullable, or `NOT NULL DEFAULT` where the database can populate existing rows.
3. **Schema expectation registry** — extend the expected table shape in the project's drift check (often `_EXPECTED_SCHEMA_STR`).
4. **Project documentation** — update the schema reference and the table-specific documentation that the project actually ships.
5. **Domain field projections** — update any field lists, serializers, or domain wrappers that enumerate the table's columns.

## For destructive operations (DROP TABLE, table rebuild, column removal)

Write a dedicated migration module with row-count validation and rehearsal
support, then run the governed migration rehearsal before live apply.
Never use raw ALTER TABLE for destructive live operations. These are
data-transforming migrations, not additive schema, so they always take the
governed path above — they do not self-propagate on boot.

## After migration

Run doctor through the canonical watcher wrapper to verify the schema matches expectations (per AGENTS.md `## Command Output — Hard Rule`):
```bash
yoke watch doctor -- --only HC-schema-drift
```

## Checklist summary

- [ ] Change classified: additive schema (self-propagates on boot) vs data-transforming migration (governed path)
- [ ] (Data-transforming migrations only) Governed migration rehearsal run before live DDL
- [ ] (Data-transforming migrations only) Governed live apply recorded a Postgres rollback dump in `migration_audit.backup_path`
- [ ] (Additive schema) Additive converger updated so the column reaches existing environments on deploy or boot
- [ ] Fresh-schema creator updated
- [ ] Idempotent column helper used in the additive converger, not a legacy-data or one-shot migration wrapper
- [ ] Schema expectation registry updated
- [ ] Project schema documentation updated
- [ ] Relevant domain field projections updated
- [ ] Dedicated migration script with row-count verification for destructive operations
- [ ] Doctor passes after migration (`yoke watch doctor -- --only HC-schema-drift`)
