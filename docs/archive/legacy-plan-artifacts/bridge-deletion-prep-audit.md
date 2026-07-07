# Bridge Deletion Receipt

Date: 2026-06-03.

Scope: GEN-3 Postgres-native bridge deletion receipt for the retired
SQLite-shaped Postgres adapter family.

## Decision

The fake SQLite-to-Postgres bridge is deleted from active runtime. The live
authority connection factory, disposable Postgres test helpers, and backend
roundtrip tests now use native psycopg connections with Postgres paramstyle.

Deleted runtime modules:

- `runtime/api/domain/db_backend_sqlite_compat.py`
- `runtime/api/domain/db_backend_pg_translate.py`
- `runtime/api/domain/db_backend_pg_shims.py`
- `runtime/api/domain/db_backend_pg_percent.py`

## Verification Snapshot

The bridge import scan is now limited to this audit artifact and historical
planning prose; there are no active runtime imports of the deleted adapter
modules or shim installer. Backend tests assert the native contract directly:

- `db_backend.connect()` returns a psycopg connection family row surface.
- SQLite `?` paramstyle is rejected on the native backend.
- Generated ids use `RETURNING`.
- JSON and time helper SQL renders in Postgres form.
- Connected-env retry tests patch the native opener, not the retired facade.

## Remaining SQLite Residue Classes

Remaining SQLite-token hits are not bridge blockers by themselves. They are
classified into these keep/retire buckets:

- archived planning and audit prose
- one-time authority import tooling
- generic external SQLite validation surfaces, including webapp template
  product data and explicit sqlite-file migration validation
- pure unit-test in-memory doubles that do not model Yoke authority
- stable guard telemetry and denial wording, including the retained
  `lint-sqlite-cmd` id

Any future cleanup should handle those buckets by their own product boundary,
not by resurrecting the deleted bridge adapter.
