# Engineer — DB Schema Changes Migration Protocol

Read before a schema change. Find this project's own owners in source first;
in Yoke they are `create_core_tables`, `apply_additive_schema`,
`_add_column_if_not_exists` and `_EXPECTED_SCHEMA_STR`. Governed history rules
live in `.yoke/docs/databases/migrations.md`.

## Classify before writing

A purely additive CREATE TABLE, ADD COLUMN or CREATE INDEX goes through
idempotent boot convergence. A backfill, drop, column removal or table rewrite
transforms data and goes through the ordered migration history.

## Additive changes

For a new column, update all five owners: the fresh-schema CREATE statement,
the additive declaration through the column helper (nullable or NOT NULL
DEFAULT, so existing rows stay valid), the schema expectation registry, the
shipped schema docs, and the domain fields, serializers and projections that
enumerate columns. New tables and indexes update the same owners.

## Data-transforming history

Author and rehearse; never apply it live. Serving boot applies it after deploy.

1. Add the next ordered `NNNN_slug.py` in the migrations package with
   `apply(conn)` and optional `invariants(conn)`. Entries are permanent.
2. Guard every statement (IF EXISTS, IF NOT EXISTS, state checks) so a replay
   is safe, and never commit inside `apply`: the applier commits the change and
   its ledger row together.
3. On PostgreSQL, a parameterized execute writes a literal percent as `%%`;
   without parameters, pass none rather than an empty tuple. Historical JSON
   text may hold escaped NUL that jsonb rejects: parse rows one at a time or
   prove each value converts, and name the row key in any skip.
4. A database already at or past the target is finished; never reject a newer
   schema.
5. Rehearse before merge with `yoke migration rehearse PREFIX-N`.

## Verify

```bash
yoke watch doctor -- --only HC-schema-drift
```
