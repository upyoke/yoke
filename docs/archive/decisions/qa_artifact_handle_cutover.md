# qa_artifact_handle_cutover — exception-path authoritative apply

- date: 2026-06-12
- pathway: `record_audit_fingerprint` exception (operator-mandated, ceremony-free)
- caller: `runtime/api/tools/apply_qa_artifact_handle_cutover.py` (one-shot; deleted with the module at retire time)

## What applied

The `qa_artifact_handle_cutover` module against the prod authoritative
Postgres: every historical `qa_artifacts` row purged (DELETE, sequence
preserved), `artifact_handle TEXT` added as the only file reference,
`storage_path` dropped.

## Why the purge is correct

Every recorded `storage_path` resolved against the recording process's
per-PID scratch directory, so the files those rows pointed at no longer
existed on any machine (field-notes 12975/13008 — the
`--absolute-paths` resolution lie). Historical QA artifacts were
explicitly declared not-needed by the operator (2026-06-12). Evidence
going forward is durable-by-construction: S3 upload at record time via
`qa.artifact.presign` + `qa.artifact.add`, or an explicit `local`
handle.

## Why the exception pathway

The item-bound governed runner (`migration_apply rehearse/live-apply`)
requires full ticket wiring; the operator overrode that ceremony for
the Gen 3 founder-build waves ("overriding all ceremony besides
worktrees and governed db migrations", 2026-06-12). The exception
pathway preserves the contract's substance:

- **Rehearsal evidence:**
  `runtime/api/domain/migrations/test_qa_artifact_handle_cutover.py`
  ran the module's `apply()` against the legacy shape plus
  `invariants()` on full-production-schema validation Postgres
  databases (`init_test_db` → `schema.cmd_init`), including an explicit
  plain-tuple-row run over `db_backend.connect_psycopg()` — green
  2026-06-12, idempotent re-apply covered.
- **Rollback:** a manual RDS cluster snapshot of `prod-db-cluster`
  precedes the apply, and `record_audit_fingerprint` creates a Postgres
  rollback dump (`backup_reason="qa-artifact-handle-cutover"`) before
  the audit row lands.
- **Discoverability:** the completed apply is a `migration_audit` row
  (`exception_reason` populated), satisfying the retire gate's
  applied-everywhere evidence under the single-authoritative-install
  topology.

DB-claim axes for the record: `migration_strategy=hard_cutover`,
`compatibility_class=pre_merge_breaking`, project posture
`founder_cutover` — first-class allow per the joint gate matrix.
