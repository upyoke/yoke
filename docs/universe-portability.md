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

## Attended production source cutover

Ordinary `yoke universe export` continues to refuse a prod-flagged connection.
The source-dev/admin cutover boundary is explicit and recoverable:

```text
yoke --env prod-db-admin source-authority quiesce begin \
  --service-stop-receipt SERVICE_STOP_ID \
  --credential-file /secure/source-cutover.json --json
yoke source-authority quiesce status \
  --credential-file /secure/source-cutover.json --json
yoke source-authority export --out /secure/source.dump \
  --credential-file /secure/source-cutover.json --json
yoke source-authority quiesce abort \
  --credential-file /secure/source-cutover.json --json
yoke source-authority quiesce retire \
  --credential-file /secure/source-cutover.json \
  --retirement-receipt RETIREMENT_GATE_ID --json
```

Stop the old API/sync/webhook service first and pass its attended stop receipt.
`begin` transactionally replaces every ordinary login's database `CONNECT`
grant with an owner-only fence, commits that durable ACL before draining every
other client session (including older sessions of the owner role), and refuses
success unless none remains. The known `rdsadmin` provider-superuser retains a
PostgreSQL-level `CONNECT` bypass that the owner ACL cannot revoke. Success
therefore proves its live sessions are **observed absent** in
`pg_stat_activity`; the fence does not enforce denial for that provider role.
Any live provider-superuser session is an explicit attended-drain blocker.
The owner must have the effective privileges of `pg_signal_backend` and
`pg_read_all_stats`; `NOINHERIT` membership alone is insufficient. Unexpected
superusers or inherited owner membership also block the operation.

The owner-only credential bundle binds the old database OID, administrator,
fence receipt, original credential, and rotated cutover credential. After
canonical machine authority switches to hosted production, `status`, `export`,
`abort`, and `retire` continue to address the old source exclusively through
that bundle; they do not re-resolve the canonical production connection.

`export` opens one read-only `REPEATABLE READ` transaction, exports its
PostgreSQL snapshot, and binds the compact receipt, detailed receipt, and
`pg_dump --snapshot` archive to that same view. It then proves the durable
fence again from a fresh connection. `abort` transactionally replays the saved,
`acldefault`-expanded effective `CONNECT` policy and removes the owner-only
control schema. The receipt preserves whether the original physical ACL was
`NULL`; PostgreSQL's supported grant/revoke DDL restores the exact effective
NULL-default semantics, though it need not reproduce the internal NULL storage
sentinel. After every recorded retirement gate passes, `retire` preserves the
control-state evidence, sets the source administrator to `NOLOGIN`, clears its
password, proves both retained credentials are rejected, and removes the local
credential bundle.

The export writes two owner-only JSON artifacts beside the archive. The compact
`.source-freeze-intent.json` is the exact `yoke.source-freeze/v1` cross-service
contract suitable for the `x-yoke-source-freeze-intent` request header; the
larger `.source-freeze-receipt.json` is the detailed audit sidecar. Neither
contains a DSN, token, or secret. Compact begin/status receipts use bounded
count/max/schema/catalog/sequence/strategy queries. The export and disposable
round-trip each perform one streaming, fixed-batch content-digest pass so a
large events table is never loaded or sorted in client memory.

Capability settings and capability secrets use separate secret-free receipt
planes grouped by capability type and project. The replacement may overlay only
explicitly named environment-owned types; it must prove exact source/restored
equality for every other capability type. Capability-secret rows never enter
the archive: the source plane records only hashes and counts, the archive
catalog proves table-data omission, and the replacement must reject any source
secret type not explicitly environment-owned before restoring the preserved
destination secrets. The whole-authority digest therefore canonicalizes this
one plane to its restored-empty value; the populated source plane remains in
the sidecar and compact intent as distinct overlay evidence. Environment,
preview-environment, and site rows remain in whole-authority equality. The
normalization receipt records the owner for every excluded table: destination
convergence, destination rebinding, destination overlay, a separate receipt
plane, or intentional retirement.

The compact intent's `database` object identifies the frozen **source**
database (name, OID, and org). It is evidence about what was exported, not a
target compare-and-swap token; a replacement service supplies and verifies its
current target database identity separately.
