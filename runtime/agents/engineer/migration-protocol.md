# Engineer — DB Schema Changes Migration Protocol

Reference content for the canonical engineer prompt at `runtime/agents/engineer.md`. Read this file before any task that modifies the database schema (ALTER TABLE, CREATE TABLE, DROP TABLE, ADD COLUMN, etc.).

**Boot-propagation doctrine:** additive schema (net-new tables/columns/indexes) self-propagates. `converge_core_schema` runs the full idempotent create/ADD-COLUMN sequence (`create_core_tables` + `apply_additive_schema`) on every server boot (`server_entrypoint.ensure_core_schema`), so an additive change reaches every already-born prod/self-host universe on the next deploy — no governed migration and no manual catch-up. The governed migration runner is only for data-transforming migrations (backfills, drops, rewrites). The drift risk to avoid: putting an additive ADD COLUMN anywhere other than `apply_additive_schema()`, which the boot converge path would then miss — and skipping the fresh-init CREATE TABLE / doctor-expected-schema updates.

## Routing: additive schema vs data-transforming migration

**First classify the change.** Pure-additive schema (net-new `CREATE TABLE`, `ADD COLUMN`, `CREATE INDEX`) needs NO governed migration and NO live DDL: you update the source (see "For new columns" below), and `converge_core_schema` — run by `server_entrypoint.ensure_core_schema` on every server boot — applies it idempotently, so the change self-propagates to every already-born prod/self-host universe on the next deploy/boot. Data-transforming migrations (backfills, drops, column removals, table rewrites) are the ONLY class that uses the governed path below.

## Before a data-transforming migration

1. **Use the governed migration-apply path for live DDL.** The intended
   agent-facing wrapper is pending; until it exists, do not invent a raw
   module recipe in task prose. Dispatch context must name the sanctioned
   migration rehearse/live-apply surface explicitly before an Engineer runs
   live DDL.
2. Verify the live-apply audit row records a non-empty `backup_path` and that
   the referenced Postgres rollback dump exists.

## For new columns (ADD COLUMN)

A pure-additive column needs NO manual live `ALTER TABLE` and NO governed migration-apply — server boot's `converge_core_schema` runs `apply_additive_schema` and propagates the column to every born universe on the next deploy/boot. Just make the code-side edits below; the column lands on existing universes on their next boot. Update ALL of these:

1. **Canonical CREATE TABLE block** — add the column to the table's `CREATE TABLE IF NOT EXISTS` statement in `create_core_tables()` (`runtime/api/domain/schema_init_tables.py`). This is the fresh-DB-init path.
2. **Additive-schema converge step** — add an `_add_column_if_not_exists(conn, "<table>", "<new_column>", "<TYPE [DEFAULT value]>")` line to `apply_additive_schema()` (`runtime/api/domain/schema_init_columns.py`), NOT `apply_legacy_data_migrations()` and NOT the `apply_idempotent_migrations()` wrapper. `apply_additive_schema()` is the strictly-additive function that `converge_core_schema` runs on every server boot, so a line added here self-propagates to every already-born universe on the next deploy/boot. The column must be self-sufficient on ADD alone — nullable, or `NOT NULL DEFAULT` (Postgres populates existing rows at ADD time). A column needing a follow-up data backfill belongs in `apply_legacy_data_migrations()`, not here. The helper guards through `schema_common` column introspection, so it is safe to re-run against existing DBs.
3. **HC-schema-drift expected schema** — extend the table's `colname/TYPE,...` section in `_EXPECTED_SCHEMA_STR` (`runtime/api/engines/doctor_hc_db_project_schema_expected.py`). The doctor HC `HC-schema-drift` reads this constant.
4. **DB reference docs** — update the CREATE TABLE block in `.yoke/docs/db-reference.md` and the relevant per-table file under `.yoke/docs/db-reference/` (for items / epic_tasks: `items-and-epics.md`).
5. **Relevant domain wrapper field lists** — when the touched table has a domain module that enumerates field names, add the new column to those lists. Examples:
   - Items columns: `runtime/api/domain/items_constants.py` (`CANONICAL_COLUMNS`, `LIST_COLUMNS`, `LARGE_TEXT_FIELDS`, `STRUCTURED_FIELDS`, `CONTENT_FIELDS`) and `runtime/api/domain/mutation_fields.py` (`SUPPORTED_UPDATE_FIELDS`).
   - Flow columns: `runtime/api/domain/flow.py` / `flow_crud.py`.
   - Ephemeral env columns: `runtime/api/domain/ephemeral_env.py`.

## For destructive operations (DROP TABLE, table rebuild, column removal)

Write a dedicated migration module with row-count validation and rehearsal
support, then run the governed migration rehearsal before live apply.
Never use raw ALTER TABLE for destructive live operations. These are
data-transforming migrations, not additive schema, so they always take the
governed path above — they do not self-propagate on boot.

## After migration

Run doctor through the canonical watcher wrapper to verify the schema matches expectations (per AGENTS.md `## Command Output — Hard Rule`):
```bash
python3 -m yoke_core.tools.watch_doctor -- --only HC-schema-drift
```

## Checklist summary

- [ ] Change classified: additive schema (self-propagates on boot) vs data-transforming migration (governed path)
- [ ] (Data-transforming migrations only) Governed migration rehearsal run before live DDL
- [ ] (Data-transforming migrations only) Governed live apply recorded a Postgres rollback dump in `migration_audit.backup_path`
- [ ] (Additive schema) ADD COLUMN line added to `apply_additive_schema()` so the column converges on next deploy/boot — no governed apply needed
- [ ] `create_core_tables()` CREATE TABLE updated (`runtime/api/domain/schema_init_tables.py`)
- [ ] `apply_additive_schema()` `_add_column_if_not_exists` line added — NOT the legacy-data tail or the `apply_idempotent_migrations()` wrapper (`runtime/api/domain/schema_init_columns.py`); this is the boot-converge, self-propagating path so the column reaches existing universes on next deploy
- [ ] `_EXPECTED_SCHEMA_STR` table section updated (`runtime/api/engines/doctor_hc_db_project_schema_expected.py`)
- [ ] `.yoke/docs/db-reference.md` + the relevant `.yoke/docs/db-reference/<topic>.md` updated
- [ ] Relevant domain wrapper field lists updated (e.g., `items_constants.py`, `mutation_fields.py`, `flow.py`, `ephemeral_env.py` — whichever domain owns the table)
- [ ] Dedicated migration script with row-count verification for destructive operations
- [ ] Doctor passes after migration (`python3 -m yoke_core.tools.watch_doctor -- --only HC-schema-drift`)
