# Universe portability, backup, and restore

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > Universe portability, backup, and restore
<!-- /yoke:breadcrumbs -->

A portable Universe archive lets you preserve your Yoke records or move them to another machine or hosting mode. Export creates one archive; import validates it and replaces the destination Universe with the saved data.

## What moves with a Universe

The archive contains the Universe database and a receipt binding that database dump to its exact contents. It preserves records such as projects, strategy documents, and work history. Exports include readable QA artifacts and shared files, with a manifest recording each file's checksum or why it is missing.

Repository folders, application databases, running agents, and external services are not part of the Universe database. Confirmed absent files remain listed as missing with `artifact_source_absent`; unavailable handles or owners use `artifact_handle_or_owner_unavailable`. The summary prints the missing count and keys. Access, credential and network failures refuse with `archive_artifact_unreadable`; repair file or store access and retry, or use `--exclude-artifacts`. A relative file path needs its project's checkout attached or registered on this machine. A file beyond the per-file limit refuses with `archive_artifact_too_large`; use `--exclude-artifacts`. Estimates apply the same rules. Refusals write no new archive. Credentials require destination-specific handling and reconnection; do not treat an archive as a way to copy working machine access unchanged.

## Export a Universe

For a local or self-host move, use `yoke universe export --pause-source`. Hosted sources use Download on the dashboard’s Move universe page. The normal CLI export directory is your machine's Yoke exports folder; choose an explicit output location when you need a backup elsewhere.

`yoke universe export --estimate --json` estimates database and artifact bytes before export. Use `--exclude-artifacts` when you only want the database and receipt.

The result is one `.tar` file. Keep the archive together: its database dump and receipt are both needed for validation and import. Store backups outside any machine home or server volume you intend to remove.

A move export checks output-folder write access before pausing. An unavailable path refuses with `universe_export_destination_unavailable` and leaves a running source running. It then disables PostgreSQL connections to the source and terminates its clients, including older engines and raw database clients. It exports a frozen database copy, requiring additional database space and source administration permission. Once paused, the source stays paused until `yoke universe resume`, including after an export failure. The summary names included artifact paths and any missing file count and keys. Export without `--pause-source` creates a backup that hosted import refuses; local import accepts it. Protected direct database connections remain refused.

## Validate and retain backups

`yoke universe validate` checks a portable archive before it is used. Validation checks the archive, receipt, manifest and every included file; it does not prove that an application, repository, or external service was also backed up.

For deeper recovery verification, the supported round-trip validation restores into an explicitly disposable PostgreSQL database. That replaces the validation target, so an operator must prepare and identify the scratch database first.

Keep a backup history appropriate to your recovery needs. Universe retention policies govern old records in the active Universe; they are not a substitute for retaining independent backups.

## Import and restore

For a new installation, setup offers **Start from a backup** when creating a local or self-hosted Universe. It validates the archive before Apply, restores the Universe, and then offers its projects so you can identify their checkouts on the new machine.

For an existing destination, import asks for the archive and consent to replace the destination Universe. Local import targets the active local connection; self-host import targets the selected server bundle. Hosted import pulls a signed archive link server-to-server from configured source buckets. For a local or self-host archive, run `yoke universe upload ARCHIVE --org SLUG`, using that destination org's hosted connection (`yoke --env DESTINATION universe upload ARCHIVE --org SLUG`). Paste the printed signed link into Import on the printed dashboard page before its expiry; slow uploads renew their URLs automatically. Hosted Download enforces a 10 GiB preflight cap and gives a link valid for one hour.

Check the destination before approving replacement. Preserve its current data if you may need it later. Import is replacement, not a merge of two backlogs. Imports place included files in the destination's storage and rewrite their handles; a destination with no configured artifact bucket uses its own permanent local storage. Review the import's missing-file count before resuming work.

## Move between hosting modes

A move combines export, destination setup, import, and reconnection. Choose the new mode based on where people and agents need to work: local is reachable on one computer; self-hosted and hosted modes support connected machines and teammates.

Avoid continuing independent work against both copies after a move. Decide which Universe is the active destination and reconnect clients to it, so new records do not diverge between the old and new installations.

See [Hosting modes](setup.hosting.md) for the choices and [Self-hosting](self-hosting.md) for server responsibilities.

## Reconnect machines and verify the destination

Imported credentials are revoked or rebound as required by the import path. Sign in again, reconnect machines, and confirm the selected Universe before resuming work. Register the appropriate repository folder for each restored project; the archive does not move those folders.

Check that expected projects, strategy documents, and work records are present, then verify the services and credentials those projects use. A successful database import does not establish that every external capability is ready.

The [portability reference](https://github.com/upyoke/yoke/blob/main/docs/universe-portability.md) describes archive validation, import boundaries, and source pause recovery.
