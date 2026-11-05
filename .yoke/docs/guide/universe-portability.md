# Universe portability, backup, and restore

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Universe portability, backup, and restore
<!-- /yoke:breadcrumbs -->

A portable Universe archive lets you preserve your Yoke records or move them to another machine or hosting mode. Export creates one archive; import validates it and replaces the destination Universe with the saved data.

## What moves with a Universe

The archive contains the Universe database and a receipt binding that database dump to its exact contents. It preserves records such as projects, strategy documents, and work history. Exports include readable QA artifacts and shared files, with a manifest recording each file's checksum or why it is missing.

Repository folders, application databases, running agents, and external services are not part of the Universe database. Confirmed absent files remain listed as missing with `artifact_source_absent`; unavailable handles or owners use `artifact_handle_or_owner_unavailable`. The summary prints the missing count and keys. Access, credential and network failures refuse with `archive_artifact_unreadable`; repair file or store access and retry, or use `--exclude-artifacts`. A relative file path needs its project's checkout attached or registered on this machine. Stored files remain exportable even when they exceed the current upload limit; export streams their bytes and records their checksums. The archive total cap still applies. Estimates apply the same rules. Refusals write no new archive. Credentials require destination-specific handling and reconnection; do not treat an archive as a way to copy working machine access unchanged.

## Export a Universe

For a local or self-host move, use `yoke universe export --pause-source`. Hosted sources use **Prepare archive** in the dashboard’s **Universe** portability controls, then **Download archive**. **Resume source** restores a paused source. The normal CLI export directory is your machine's Yoke exports folder; choose an explicit output location when you need a backup elsewhere.

`yoke universe export --estimate --json` estimates database and artifact bytes before export. The database estimate uses live row counts and column widths from PostgreSQL statistics, plus TOAST storage for large values, excluding indexes and reusable heap space. Tables without statistics use their table storage size instead. After pruning, `VACUUM ANALYZE` updates the statistics used by the estimate. The estimate can differ from the archive size; export and staging byte limits still apply. Use `--exclude-artifacts` when you only want the database and receipt.

The result is one `.tar` file. Keep the archive together: its database dump and receipt are both needed for validation and import. Store backups outside any machine home or server volume you intend to remove.

A move export checks output-folder write access before pausing. An unavailable path refuses with `universe_export_destination_unavailable` and leaves a running source running. It then disables PostgreSQL connections to the source and terminates its clients, including older engines and raw database clients. It exports a frozen database copy, requiring additional database space and source administration permission. Once paused, the source stays paused until `yoke universe resume`, including after an export failure. The summary names included artifact paths and any missing file count and keys. Export without `--pause-source` creates a backup that hosted import refuses; local import accepts it. Protected direct database connections remain refused.

## Validate and retain backups

`yoke universe validate` checks a portable archive before it is used. Validation checks the archive, receipt, manifest and every included file; it does not prove that an application, repository, or external service was also backed up.

If validation reports `archive_tool_version_unsupported`, set `YOKE_PG_BIN_DIR` to the bin directory of PostgreSQL client tools matching the source dump writer or newer, or run `yoke init --local` to fetch Yoke's bundled tools, then retry. Preserve the original archive and receipt; an incompatible reader does not establish archive corruption.

For deeper recovery verification, the supported round-trip validation restores into an explicitly disposable PostgreSQL database. That replaces the validation target, so an operator must prepare and identify the scratch database first.

Keep a backup history appropriate to your recovery needs. Universe retention policies govern old records in the active Universe; they are not a substitute for retaining independent backups.

## Import and restore

For a new installation, setup offers **Start from a backup** when creating a local or self-hosted Universe. It validates the archive before Apply, restores the Universe, and then offers its projects so you can identify their checkouts on the new machine.

For an existing destination, import asks for the archive and consent to replace the destination Universe. Local import targets the active local connection; self-host import targets the selected server bundle. Hosted import pulls a signed archive link server-to-server from configured source buckets. For a local or self-host archive, run `yoke universe upload ARCHIVE --org SLUG`, using that destination org's hosted connection (`yoke --env DESTINATION universe upload ARCHIVE --org SLUG`). Paste the printed signed link into Import on the printed dashboard page before its expiry; slow uploads renew their URLs automatically. Hosted Prepare archive enforces a 10 GiB preflight cap and gives a link valid for one hour.

Check the destination before approving replacement. Hosted Import offers a backup first; the replacement is final, and you restore the previous destination by importing that backup. Preserve its current data if you may need it later. Import is replacement, not a merge of two backlogs. Imports place included files in the destination's storage and rewrite their handles; a destination with no configured artifact bucket uses its own permanent local storage. Review the import's missing-file count before resuming work.

## Move between hosting modes

A move combines export, destination setup, import, and reconnection. Choose the new mode based on where people and agents need to work: local is reachable on one computer; self-hosted and hosted modes support connected machines and teammates.

Avoid continuing independent work against both copies after a move. Decide which Universe is the active destination and reconnect clients to it, so new records do not diverge between the old and new installations.

See [Hosting modes](setup.hosting.md) for the choices and [Self-hosting](self-hosting.md) for server responsibilities.

## Reconnect machines and verify the destination

Local import binds the machine owner to the oldest active human in the archive and grants that actor admin authority. Disabled humans are never selected. If none is active, `local_import_no_active_human` refuses the import; ask a source org admin to enable a human, export a new archive, and retry.

Imported credentials are revoked or rebound as required by the import path. Sign in again, reconnect machines, and confirm the selected Universe before resuming work. Register the appropriate repository folder for each restored project; the archive does not move those folders.

Check that expected projects, strategy documents, and work records are present, then verify the services and credentials those projects use. A successful database import does not establish that every external capability is ready.

For exact archive and recovery procedures, use the sections below.

## Archive contents and validation

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
files from each project's store. It downloads up to 8 files at once and
writes the manifest in source order. Confirmed absent files appear as `missing`
entries with
`artifact_source_absent`; unavailable handles or owners retain
`artifact_handle_or_owner_unavailable`. Both export summaries print the missing
count and keys. Access, credential, network and other read failures refuse with
`archive_artifact_unreadable` for the first failing file in source order:
repair access and retry, or use
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
asked for a hash or receipt text. Every hosting mode validates the same archive format.

Validate the receipt binding, bounded archive structure, and table-data
catalog before moving a file:

```bash
yoke universe validate ~/backups/acme-universe-20260714T120000Z.tar
```

## Import: one file, one consent

For a new install, run `yoke setup`, choose **This machine** or **Host a server
here**, then **Start from a backup**. Setup validates the portable archive
before offering **Apply**. Apply runs the existing import and establishes the
new connection before the Project step offers the restored projects. The
backup carries the account, so setup skips the name prompt. See
[Install](../start/install.md#onboard-wizard) for the complete setup route.

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
`pg_restore` cannot read the dump format. Set `YOKE_PG_BIN_DIR` to the bin
directory of PostgreSQL client tools matching the source dump writer or newer,
or run `yoke init --local` to fetch Yoke's bundled tools, then retry validation
or import. Preserve the
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
requires `True`. Protected direct Postgres connections remain refused. The CLI refuses hosted
HTTPS sources before engine access and points to the dashboard Universe portability controls and **Prepare archive**.

Self-host import failures retain redacted exec stderr and the last 200 container
log lines before removing the one-off import container. Failure details report
exec, wait and container exit codes, OOM state and the memory limit; exec
stdout is also redacted when an image sends its refusal through that stream.
Docker output stays out of the refusal message. Read the printed details even with `--json`, repair the named cause,
and retry the import against the stopped destination bundle. The self-host image
pins its PostgreSQL clients outside the machine home and persistent volume, so
imports use the packaged tools even when Compose selects a different home.
An import supervisor keeps the container alive until the private exec bridge
returns. The host then finishes the supervisor and checks the importer exit
code; a killed bridge always fails, even if it emitted a partial receipt.
Completion signals only set a flag; deadline polling bounds the bridge wait
without taking a lock inside the signal handler.

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
