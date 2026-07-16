# Universe portability

A universe IS a database: export is a dump, import is a restore-and-switch.
The portable artifact is ONE tar file, `<org-slug>-universe-<utc-timestamp>.tar`,
carrying exactly two members at its root:

- `universe.dump` — the `pg_dump` custom-format payload
  (compressed, `pg_restore --list`-able).
- `freeze-receipt.json` — the freeze receipt whose `freeze_intent.archive`
  block binds that exact payload by SHA-256 and byte count.

The receipt travels inside the artifact, so every importer — local CLI,
self-host bundle, hosted platform — derives checksum verification from the
file itself. Humans move one file between machines and modes and are never
asked for a hash or receipt text. The format owner is
`yoke_core.domain.universe_archive` (pack, unpack, receipt build, and
verification); every mode shares those helpers.

Validate the receipt binding, bounded archive structure, and table-data
catalog before moving a file:

```bash
yoke universe validate ~/backups/acme-universe-20260714T120000Z.tar
```

Release and migration rehearsals may also restore into an explicitly
disposable Postgres database. Point `YOKE_PG_DSN_VALIDATION` at that scratch
database, attest that it is disposable, and request the round trip:

```bash
YOKE_UNIVERSE_VALIDATION_DISPOSABLE=1 \
  yoke universe validate ~/backups/acme-universe-20260714T120000Z.tar --roundtrip
```

The round trip replaces whatever the disposable database holds — exactly like
a real import destination — and emits organization, project, schema, and
content-count receipts without printing credentials. Never use a production
database as the validation target.

## Import: one file, one consent

`yoke self-host import ARCHIVE` asks the operator exactly two things: which
archive, and consent to replace the destination universe (`--yes` for
non-interactive runs). Everything else — checksum, receipt verification,
catalog compatibility — is derived from the archive. The destination is reset
and restored through one path whether it was brand-new or held a prior
universe; replacing the current universe is the operator's call, which is why
the consent stays.

## Attended production source cutover

Ordinary `yoke universe export` continues to refuse a prod-flagged connection.
The source-dev/admin cutover boundary is explicit and recoverable:

```text
yoke --env prod-db-admin dev db-admin setup prod --project platform \
  --prod --yes --json
yoke --env prod-db-admin source-authority quiesce begin \
  --service-stop-receipt SERVICE_STOP_ID \
  --credential-file /secure/source-cutover.json --json
yoke source-authority quiesce status \
  --credential-file /secure/source-cutover.json --json
yoke source-authority export --out /secure/source.tar \
  --credential-file /secure/source-cutover.json --json
yoke source-authority quiesce abort \
  --credential-file /secure/source-cutover.json --json
yoke source-authority quiesce retire \
  --credential-file /secure/source-cutover.json \
  --retirement-receipt RETIREMENT_GATE_ID --json
```

The explicit `--prod` marker is mandatory. It records production authority in
the machine connection without inferring safety policy from an environment
name, database name, or DSN; the source-authority boundary refuses profiles
that omit it. `--project platform` selects the project that owns Yoke's
deployment environments and infrastructure, while `prod` selects that
project's Production environment.

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
fence receipt, original credential, and rotated cutover credential. Rotation
proves the original credential connected before the committed `ALTER ROLE`,
the generated cutover secret is distinct, and a fresh cutover-secret connection
succeeds afterward. PostgreSQL stores one password verifier per role, so this
proves supersession without reading provider-restricted password catalogs;
connection-error text is not cutoff evidence.
After canonical machine authority switches to hosted production, `status`, `export`,
`abort`, and `retire` continue to address the old source exclusively through
that bundle; they do not re-resolve the canonical production connection.

`export` opens one read-only `REPEATABLE READ` transaction, exports its
PostgreSQL snapshot, and binds the compact receipt, detailed receipt, and
`pg_dump --snapshot` archive to that same view. It then proves the durable
fence again and requires an exact fresh full-authority receipt from a new
connection; a committed writer that appeared and exited during the dump still
invalidates publication. `abort` transactionally replays the saved,
`acldefault`-expanded effective `CONNECT` policy and removes the owner-only
control schema. The receipt preserves whether the original physical ACL was
`NULL`; PostgreSQL's supported grant/revoke DDL restores the exact effective
NULL-default semantics, though it need not reproduce the internal NULL storage
sentinel. After every recorded retirement gate passes, `retire` preserves the
control-state evidence, sets the source administrator to `NOLOGIN`, clears its
password, proves that state through the still-live administrator session, and
removes the local credential bundle. A persisted transaction marker plus an
exact single-host `NOLOGIN` response supports crash recovery; generic password,
network, TLS, timeout, and multi-host text never counts as cutoff evidence.

The export writes exactly one artifact: the tar described at the top of this
page. Its `freeze-receipt.json` member carries the compact
`yoke.source-freeze/v1` intent (under `freeze_intent`), the detailed authority
audit receipt (under `source_authority`), and the archive data catalog (under
`catalog`); a replacement service reads all of them from inside the archive.
None contains a DSN, token, or secret. Compact begin/status receipts use
bounded count/max/schema/catalog/sequence/strategy queries. The export and
disposable round-trip each perform one streaming, fixed-batch content-digest
pass so a large events table is never loaded or sorted in client memory.

The dump payload is staged under an owner-only hidden sibling name, the tar is
assembled receipt-first in a private temporary file, and the final archive
name appears atomically (`os.replace`), so no partial or receipt-less artifact
ever exists under the destination name.

Capability settings and capability secrets use separate secret-free receipt
planes grouped by capability type and project. The replacement may overlay only
explicitly named environment-owned types; it must prove exact source/restored
equality for every other capability type. Capability-secret rows never enter
the archive: the source plane records only hashes and counts, the archive
catalog proves table-data omission, and the replacement must reject any source
secret type not explicitly environment-owned before restoring the preserved
destination secrets. The whole-authority digest therefore canonicalizes this
one plane to its restored-empty value; the populated source plane remains in
the detailed receipt and compact intent as distinct overlay evidence. Environment,
preview-environment, and site rows remain in whole-authority equality. The
normalization receipt records the owner for every excluded table: destination
convergence, destination rebinding, destination overlay, a separate receipt
plane, or intentional retirement.

The compact intent's `database` object identifies the frozen **source**
database (name, OID, and org). It is evidence about what was exported, not a
target compare-and-swap token; a replacement service supplies and verifies its
current target database identity separately.
