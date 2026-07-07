# YOK-1896 Migration Handoff

YOK-1896 migrated the Yoke control-plane data set from the canonical local SQLite DB into the `yoke-prod` Aurora PostgreSQL database provisioned by YOK-1894.

## Completed

- Resolved `yoke-prod` Pulumi outputs from `s3://yoke-pulumi-state?region=us-east-1`.
- Used Yoke `aws-admin` capability secrets to read AWS state and the RDS secret without printing secret values.
- Used a temporary EC2 Instance Connect key under `/tmp` to tunnel through origin `52.20.177.138`.
- Archived SQLite source DB to `/Users/dev/yoke/data/backups/yoke-authority/yoke.20260601T023602Z.pre-aurora.sqlite3`.
- Reset Aurora `public`, initialized compatibility schema, dynamically created source-only tables/indexes, reconciled missing source columns, copied 52 tables and 1,550,306 rows.
- Recorded completed migration audit row on Aurora for `yoke_sqlite_to_aurora_authority`.
- Verified exact table set and row counts with the expected `migration_audit +1` delta.
- Proved `pg_dump`/restore against migrated data in scratch DB `sun1896_restore_20260531223848`; scratch DB was dropped.
- Proved local function-backed Yoke read/write using `YOKE_BACKEND=postgres` and `YOKE_PG_DSN_FILE=/tmp/sun1896-target.dsn`.

## Follow-Up

- Remove `/tmp/sun1896-*` files and close `/tmp/sun1896-ssh-ctl` tunnel after review.
- Keep the archived SQLite DB only as the short rollback artifact until connected-env and Postgres-native cleanup slices retire it.
- File a follow-up to move Yoke/Buzz SSH private-key material into `capability_secrets` and leave only non-sensitive SSH metadata in `project_capabilities.settings`.
- G3.P1.I5 must provide connected-env binding so harnesses and hooks can use Aurora without per-command env prefixes.
- G3.P1.I7 must retire SQLite runtime assumptions and the transitional compatibility bridge.
