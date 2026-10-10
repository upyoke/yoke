# Engineer — DB Schema Changes Migration Protocol

Read before schema changes. First discover this project's fresh-schema creator,
additive converger, column helper and expectation registry in verified source.
Common Yoke names `create_core_tables`, `apply_additive_schema`,
`_add_column_if_not_exists`, `_EXPECTED_SCHEMA_STR` are search hints, not paths.

## Classify before writing

Pure-additive CREATE TABLE/ADD COLUMN/CREATE INDEX follows verified idempotent
boot convergence; no manual live DDL or governed apply when it handles the change.
Backfills/drops/column removals/table rewrites are data transformations and use
governed history. Never borrow another project's owner or convergence assumptions.

## Data-transforming history

Author and rehearse; do not apply live. Serving boot applies after merge/deploy,
before serving. Read AGENTS databases depth for all governed requirements.

1. Add next ordered `NNNN_slug.py` in model migrations: `apply(conn)`, optional
   `invariants(conn)`. Entries are permanent; never delete a module a universe
   might not yet have received. **Never delete it afterwards.**
2. Guard every statement (IF EXISTS/IF NOT EXISTS/state checks) for restored
   pre-ledger archive replay. **Never commit inside apply**: applier atomically
   commits mutation plus ledger, avoiding applied-but-unrecorded state.
3. PostgreSQL parameterized execute/executemany escapes literal percent as `%%`;
   keep `%s`, `%b`, `%t`, `%(name)s` unchanged. Without placeholders omit params,
   rather than empty params. Historical JSON text is untrusted: valid JSON can
   contain escaped NUL unsuitable for jsonb. Parse rows independently or prove
   each value convertible before casting; retain row keys in diagnosis/skips.
   Never cast whole historical text column blindly.
4. Rehearse before merge from item's configured local-Postgres authority:
   `yoke migration rehearse PREFIX-N`. Missing authority goes to control-plane
   operator. Receipt proves validation surface and evidence gate; migration
   territory lease remains held against competing work. Required live-universe
   rehearsals and fleet receipts remain governed by databases depth.
5. Already at/beyond target means finished. Do not reject newer schema versions:
   permanent entries must continue booting after their original shape changes.

## Additive schema owners

For new columns update all five:
- Fresh-schema CREATE statement.
- Idempotent additive declaration via project's column helper, never legacy
  data/one-shot wrapper. Added column must populate existing rows safely:
  nullable or NOT NULL DEFAULT.
- Drift/schema expectation registry.
- Shipped schema/table documentation.
- Enumerated domain fields, serializers and projections.

New tables/indexes likewise update their verified creation/convergence/docs/
expectation owners. No raw destructive live ALTER. Drop/rebuild/removal uses
guarded permanent history with row-count validation and rehearsal support.

## Verify after convergence

```bash
yoke watch doctor -- --only HC-schema-drift
```

Before submission confirm classification, permanent guarded/noncommitting
history and receipt where required, PostgreSQL percent/JSON handling,
fresh/additive/helper/expectation/docs/projection updates, destructive row-count
proof and post-migration doctor result. Source authoring is not live application.
