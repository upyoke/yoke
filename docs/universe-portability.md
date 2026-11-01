# Universe portability

A universe archive carries the database and its portable artifact files.
The dump selects only the `public` schema and excludes capability-secret data.
Environment-owned instrumentation schemas, extensions, and source-authority
fence state stay on the source; import keeps its strict public-only catalog checks.
This database boundary applies to local, self-hosted, and hosted exports.

The portable artifact is ONE tar file, `<org-slug>-universe-<utc-timestamp>.tar`,
carrying the following required members at its root:

- `universe.dump` — the `pg_dump` custom-format payload
  (compressed, `pg_restore --list`-able).
- `freeze-receipt.json` — the freeze receipt whose `freeze_intent.archive`
  block binds that exact payload by SHA-256 and byte count.

Archives with artifact bytes also include `artifacts-manifest.json` and an
`artifacts/` tree. Each manifest entry names its original handle, a store-neutral
`qa-artifacts/...` or `shared-files/...` key, status, and (when included) its
SHA-256 and byte count. The freeze receipt binds the manifest's SHA-256 as
`freeze_intent.archive.artifacts_manifest_sha256`. Validation verifies every
included file and refuses extra, unsafe, missing or tampered members.
Two-member archives remain valid and restore their database as before.

Export reads each QA handle from its named local or S3 store and lists shared
files from each project's store. Confirmed absent files appear as `missing`
entries with
`artifact_source_absent`; unavailable handles or owners retain
`artifact_handle_or_owner_unavailable`. Both export summaries print the missing
count and keys. Access, credential, network and other read failures refuse with
`archive_artifact_unreadable`: repair access and retry, or use
`--exclude-artifacts`. Relative handles require the project's checkout on this
machine; attach or register it and retry. Stored files above the current upload
limit remain exportable; the streaming copy records their full byte counts and
checksums. The archive total cap remains. Estimates apply the same classification. Refusals write no new archive. A source paused by
`--pause-source` stays paused; run `yoke universe resume` when it may write again.
A store that cannot list shared files refuses rather than omitting unknown files.
`--exclude-artifacts` exports only the database and receipt.
`yoke universe export --estimate --json` reports a database-size estimate plus
artifact bytes, file and missing counts without making a dump; the database-size
estimate is not a compressed dump size. Both options also work through the
authenticated self-host export endpoint.

Local and self-host imports capture destination storage routing before replacing
the database, write files to that store, and rewrite QA handles. Imported source
bucket settings never select the write destination. A new local or self-host
destination without configured storage uses its own permanent application-data
tree. Missing source files remain reported in the import result; included bytes
are verified before any restore. Self-host imports run inside the core container,
so local files live on the server's persistent application-data volume.
Hosted import restores included artifacts to destination storage before the org serves; no separate source-bucket copy is needed.

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
disposable Postgres database, bound as `YOKE_PG_DSN_VALIDATION` — exported, or
written to the machine-local binding file the rehearsal provisioner leaves
behind (`yoke migration rehearse --help` carries that recipe). Bind that
scratch database, attest that it is disposable, and request the round trip:

```bash
YOKE_UNIVERSE_VALIDATION_DISPOSABLE=1 \
  yoke universe validate ~/backups/acme-universe-20260714T120000Z.tar --roundtrip
```

The round trip replaces whatever the disposable database holds — exactly like
a real import destination — and emits organization, project, schema, and
content-count receipts without printing credentials. Never use a production
database as the validation target.

## Import: one file, one consent

For a new install, run `yoke setup`, choose **This machine** or **Host a server
here**, then **Start from a backup**. Setup validates the portable archive
before offering **Apply**. Apply runs the existing import and establishes the
new connection before the Project step offers the restored projects. The
backup carries the account, so setup skips the name prompt. See
[Install](public/start/install.md#onboard-wizard) for the complete setup route.

`yoke universe import ARCHIVE` and `yoke self-host import ARCHIVE` ask the
operator exactly two things: which
archive, and consent to replace the destination universe (`--yes` for
non-interactive runs). Everything else — checksum, receipt verification,
catalog compatibility — is derived from the archive. The destination is reset
and restored through one path whether it was brand-new or held a prior
universe; replacing the current universe is the operator's call, which is why
the consent stays. Local import addresses only the active `local` connection;
self-host import addresses an explicitly selected Compose bundle.

If inspection reports `archive_tool_version_unsupported`, the selected
`pg_restore` cannot read the dump format. Use PostgreSQL client tools matching
the source dump writer or newer, then retry validation or import. Preserve the
original archive and its receipt; a tool mismatch does not establish corruption.

## Export a move or a backup

Prune unwanted records and artifacts, then estimate before pausing a source.
Hosted sources use **Prepare archive** in the dashboard's **Universe**
portability controls.
Hosted size preflight enforces the 10 GiB cap before pausing; the signed link
expires after one hour. **Prepare archive** shows polled named phases with
elapsed seconds and bytes; the result offers **Download archive**, **Copy link**,
and an absolute expiry. **Resume source** restores writers explicitly. Import
shows fetching, verification, destination checks and replacement before receipt
status; refusals and recovery remain in the active dialog. Import pulls an allowlisted signed link server-to-server,
so archive bytes do not pass through a browser upload.

Local and self-host sources use:

```text
yoke universe export --estimate --json
yoke universe export --pause-source --out /secure/source.tar
yoke universe validate /secure/source.tar
```

Export checks output-folder write access before pausing; an unavailable path
refuses with `universe_export_destination_unavailable` and leaves a running
source running. The completion summary names included artifact paths and missing file counts and keys.
The pause stops the selected source's installed relay, sets PostgreSQL's
`ALLOW_CONNECTIONS=false` on the source database and terminates its existing
sessions. Older engines and raw PostgreSQL clients cannot reconnect, even as the
cluster superuser. Export uses a frozen copy of that closed database and preserves
the original source name and OID in its receipt. A private pause record binds that
copy to the source; it remains until successful Resume. This needs space for an
additional database copy, maintenance-database access, database creation authority
and permission to terminate source sessions. Failure after pausing keeps the source closed and
names recovery; retry paused export or explicitly Resume it.

Server startup and import coordinate through a read-only advisory-lock connection
to the maintenance database, scoped to this source. That lock survives the source
pause. A restarted paused server reads token and permission state from the frozen
copy, preserving authentication checks without writing token telemetry. Explicit
Resume reopens the original for schema preparation, restores its stopped relay,
and removes the copy and pause record. If preparation fails, it closes and drains
the source again and refreshes the frozen copy; writes accepted during that
explicit Resume attempt remain in the source. A failed fence or copy recovery is
reported and requires database administration access before retrying.

The self-host bundle persists its machine home, pause marker and local artifacts
on the corestate volume across container replacement. An older bundle without
an explicit persistent machine home refuses paused export and names its refresh
command. Clients also refuse a paused export when the server cannot confirm
stopped writers. Self-host request admission
refuses work while paused; restarted servers keep that pause and defer schema
preparation until explicit Resume. Self-host start and upgrade report that the
source remains paused and name Resume; they do not claim it is ready for work.
Local database acquisition
refuses connections to that source. Run `yoke universe resume` against that same
source when it may write again. A pause-marker or drain failure refuses the move
with recovery; repair the named cause and retry, or explicitly resume the source.
Unrelated databases and their services stay independent. Run a source export from a standalone terminal if it is itself
running under that source relay.

Export without `--pause-source` is a backup with
`zero_writable_app_sessions=False`; local import accepts it, hosted replacement
requires `True`. The shared `universe_snapshot_archive.snapshot_archive` function
binds the dump, artifact manifest, and receipt to one exported PostgreSQL
`REPEATABLE READ` snapshot. Its caller supplies the stopped-writer evidence.
Platform adopts this shared function through its own release-gated update.
Protected direct Postgres connections remain refused. The CLI refuses hosted
HTTPS sources before engine access and points to the dashboard Universe portability controls and **Prepare archive**.

## Upload and finish hosted import

For a local or self-host archive, use `yoke universe upload ARCHIVE --org SLUG`
with a destination hosted connection. Upload streams directly to signed multipart
storage targets, renewing URLs during slow transfers. The selected connection must
belong to --org; choose it with `yoke --env DESTINATION universe upload ARCHIVE
--org SLUG`. Upload prints a fresh signed source link and its expiry; paste it into
Import on the printed dashboard page. Failed uploads leave the source paused
until explicit Resume. Hosted-to-hosted
moves paste the source's signed link into Import. An expired link requires a fresh
export or upload; the destination accepts only configured source buckets.

Import replaces the destination universe, restores artifact bytes before serving,
and reports its receipt. Verify project, item and actor counts and sample artifact
reads. Reconnect machines using destination-issued credentials. Resume the source
if it must continue serving other people; otherwise retire it only after checking
the destination and preserving recovery evidence. Avoid writes to both copies.

## Receipt contract

The export writes exactly one artifact: the tar described at the top of this
page. Its `freeze-receipt.json` member carries the compact
`yoke.source-freeze/v2` intent (under `freeze_intent`), the detailed authority
audit receipt (under `source_authority`), and the archive data catalog (under
`catalog`); a replacement service reads all of them from inside the archive.
None contains a DSN, token, or secret. The export and disposable round-trip each perform one streaming, fixed-batch content-digest
pass, so no table is ever loaded or sorted in client memory.

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
plane, intentional retirement, or disposable telemetry.

Telemetry is outside authority equality. Event rows are disposable: one
emitted, pruned, or never written between two receipts is not a change of
authority, and counting it as one made a live export refuse a universe
nothing had altered. So `events` is excluded from the authority receipt
under the `disposable_telemetry` owner — no per-table count, no max id, no
content digest, no `events_id_seq` value — and the compact intent carries no
event watermark. What still covers events is unchanged: the table stays in
the full database catalog and the schema fingerprint, so a missing, renamed,
or reshaped events table still fails; and every event row still travels
inside the dump under the archive's exact byte checksum, so an
events-carrying diagnostic export is unaffected and is never a prerequisite
for a valid move. Both contract versions carry that boundary in their names
(`yoke.source-freeze/v2`, `yoke.portable-authority/v2`), so a consumer
pinned to the earlier shape fails on the version rather than on a silently
missing key.

The compact intent's `database` object identifies the frozen **source**
database (name, OID, and org). It is evidence about what was exported, not a
target compare-and-swap token; a replacement service supplies and verifies its
current target database identity separately.


## Hosted import into a different tenant

Platform owns hosted tenant replacement. Before minting destination credentials,
its import calls `universe_import_credentials.revoke_imported_credentials(conn)`:
all copied API tokens and browser sessions become revoked, and no token is minted.
The caller owns commit and supplies fresh destination authority separately.

Artifact import restores manifest-bound bytes into destination storage and rewrites
handles using captured destination routing. Source bucket settings never choose
the write destination. Copied API tokens and browser sessions are revoked before
fresh destination authority is issued; archives do not copy working machine access.
