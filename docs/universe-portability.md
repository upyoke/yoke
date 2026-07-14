# Universe portability

Use the custom-format universe archive to move a local or self-hosted universe
without exposing its database credentials.

Validate the bounded archive structure and table-data catalog before moving or
uploading a file:

```bash
yoke universe validate ~/backups/universe.dump
```

Release and migration rehearsals may also restore into an explicitly empty,
disposable Postgres database. Point `YOKE_PG_DSN_VALIDATION` at that scratch
database, attest that it is disposable, and request the round trip:

```bash
YOKE_UNIVERSE_VALIDATION_DISPOSABLE=1 \
  yoke universe validate ~/backups/universe.dump --roundtrip
```

The command refuses a non-empty target and emits organization, project, schema,
and content-count receipts without printing credentials. Never use a production
database as the validation target.
