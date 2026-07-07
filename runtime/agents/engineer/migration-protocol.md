# Engineer — DB Schema Changes Migration Protocol

Reference content for the canonical engineer prompt at `runtime/agents/engineer.md`. Read this file before any task that modifies the database schema (ALTER TABLE, CREATE TABLE, DROP TABLE, ADD COLUMN, etc.). Skipping these steps causes schema drift that breaks fresh DB init and doctor health checks.

## Before any schema change

1. **Use the governed migration-apply path for live DDL.** The intended
   agent-facing wrapper is pending; until it exists, do not invent a raw
   module recipe in task prose. Dispatch context must name the sanctioned
   migration rehearse/live-apply surface explicitly before an Engineer runs
   live DDL.
2. Verify the live-apply audit row records a non-empty `backup_path` and that
   the referenced Postgres rollback dump exists.

## For new columns (ADD COLUMN)

After running the ALTER TABLE against the live DB, update ALL of these:

1. **Canonical CREATE TABLE block** — add the column to the table's `CREATE TABLE IF NOT EXISTS` statement in `create_core_tables()` (`runtime/api/domain/schema_init_tables.py`). This is the fresh-DB-init path.
2. **Idempotent migration** — add an `_add_column_if_not_exists(conn, "<table>", "<new_column>", "<TYPE [DEFAULT value]>")` line to `apply_idempotent_migrations()` (`runtime/api/domain/schema_init_columns.py`). The helper guards through `schema_common` column introspection, so it is safe to re-run against existing DBs.
3. **HC-schema-drift expected schema** — extend the table's `colname/TYPE,...` section in `_EXPECTED_SCHEMA_STR` (`runtime/api/engines/doctor_hc_db_project_schema_expected.py`). The doctor HC `HC-schema-drift` reads this constant.
4. **DB reference docs** — update the CREATE TABLE block in `docs/db-reference.md` and the relevant per-table file under `docs/db-reference/` (for items / epic_tasks: `items-and-epics.md`).
5. **Relevant domain wrapper field lists** — when the touched table has a domain module that enumerates field names, add the new column to those lists. Examples:
   - Items columns: `runtime/api/domain/items_constants.py` (`CANONICAL_COLUMNS`, `LIST_COLUMNS`, `LARGE_TEXT_FIELDS`, `STRUCTURED_FIELDS`, `CONTENT_FIELDS`) and `runtime/api/domain/mutation_fields.py` (`SUPPORTED_UPDATE_FIELDS`).
   - Flow columns: `runtime/api/domain/flow.py` / `flow_crud.py`.
   - Ephemeral env columns: `runtime/api/domain/ephemeral_env.py`.

## For destructive operations (DROP TABLE, table rebuild, column removal)

Write a dedicated migration module with row-count validation and rehearsal
support, then run the governed migration rehearsal before live apply.
Never use raw ALTER TABLE for destructive live operations.

## After migration

Run doctor through the canonical watcher wrapper to verify the schema matches expectations (per AGENTS.md `## Command Output — Hard Rule`):
```bash
python3 -m yoke_core.tools.watch_doctor -- --only HC-schema-drift
```

## Checklist summary

- [ ] Governed migration rehearsal run before live DDL
- [ ] Governed live apply recorded a Postgres rollback dump in `migration_audit.backup_path`
- [ ] `create_core_tables()` CREATE TABLE updated (`runtime/api/domain/schema_init_tables.py`)
- [ ] `apply_idempotent_migrations()` `_add_column_if_not_exists` line added (`runtime/api/domain/schema_init_columns.py`)
- [ ] `_EXPECTED_SCHEMA_STR` table section updated (`runtime/api/engines/doctor_hc_db_project_schema_expected.py`)
- [ ] `docs/db-reference.md` + the relevant `docs/db-reference/<topic>.md` updated
- [ ] Relevant domain wrapper field lists updated (e.g., `items_constants.py`, `mutation_fields.py`, `flow.py`, `ephemeral_env.py` — whichever domain owns the table)
- [ ] Dedicated migration script with row-count verification for destructive operations
- [ ] Doctor passes after migration (`python3 -m yoke_core.tools.watch_doctor -- --only HC-schema-drift`)
