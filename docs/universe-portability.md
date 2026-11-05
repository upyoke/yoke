# Universe portability implementation

User procedures live in [Universe portability](public/guide/universe-portability.md).

## Disposable restore rehearsal

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

## Source coordination

Server startup and import coordinate through a read-only advisory-lock connection
to the maintenance database, scoped to this source. That lock survives the source
pause. A restarted paused server reads token and permission state from the frozen
copy, preserving authentication checks without writing token telemetry. Explicit
Resume reopens the original for schema preparation, restores its stopped relay,
and removes the copy and pause record. If preparation fails, it closes and drains
the source again and refreshes the frozen copy; writes accepted during that
explicit Resume attempt remain in the source. A failed fence or copy recovery is
reported and requires database administration access before retrying.


## Source coordination

The shared `universe_snapshot_archive.snapshot_archive` function
binds the dump, artifact manifest, and receipt to one exported PostgreSQL
`REPEATABLE READ` snapshot. Its caller supplies the stopped-writer evidence.
Platform adopts this shared function through its own release-gated update.
