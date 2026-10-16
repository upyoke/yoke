# Concurrent event retention index

Universe prune deletes expired events one bounded cohort at a time. Once most
expired rows are gone, a cohort read ordered by `id` must walk nearly the
whole events heap to find the last eligible rows; on a large universe that
exceeds the pass budget, so the table can never finish. Prune therefore reads
each retention slice separately: every event-name override and every severity
is an `ORDER BY created_at` range bounded by its own cutoff. Name overrides use
`idx_events_created_at`. Severity slices need `idx_events_severity_created`
on `events(severity, created_at)`.

`events_retention_index.ensure_retention_index` owns that one additive index
and follows the [event function index](events-function-index.md) design:
PostgreSQL requires concurrent index creation outside a transaction, so the
helper opens an autocommit connection to the caller's exact database, checks
serving-build authority, serializes competing boots with a session advisory
lock, builds concurrently, and validates the catalog. Event writers keep
inserting. An interrupted build leaves an invalid index; the retry drops only
this named index after confirming its table and columns, then rebuilds.

This is a named `record_audit_fingerprint` exception to transactional DDL.
The receipt uses `exception_reason=events-retention-index`; no rollback copy
is needed because no table, column or row is rewritten or removed.
`events_retention_index.BOOTSTRAP_AUDIT_RECORD` declares the exact arguments.

Boot convergence builds the index after the audit table is committed. The
permanent ordered entry `0080_events_retention_index` invokes the same helper
and verifies readiness before its history membership is recorded; on a
booted database it only verifies. Production receives the index through the
serving release's boot.
