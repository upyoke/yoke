# Concurrent event function index

The event ledger retains function calls whose unrelated response payloads can
be large. Full-history claim diagnostics cannot repeatedly decode every such
payload within their existing 45-second deadline. A partial expression index
on the decoded function identity gives those diagnostics the same complete
candidate set through a keyed lookup. It uses the existing NUL-safe JSON
decoder, includes every function-call event, and imposes no time cutoff.
Keys retain the first 64 decoded characters so an oversized unrelated
identifier cannot exceed PostgreSQL's B-tree key limit. Every audited family
plus its dot fits within that bound; candidates are still classified using
their full decoded identifier, including unknown functions in those families.

`events_function_index.ensure_function_index` owns one additive index,
`idx_events_function_identity`. PostgreSQL requires concurrent index creation
outside a transaction. This helper therefore opens an autocommit connection
to the exact database of the caller, checks serving-build authority, serializes
competing boots with a session advisory lock, builds concurrently, and validates
the catalog. Event writers remain free to insert. A failed concurrent build
can leave an invalid index; retry drops only this named index after verifying
its table and operator class, then rebuilds concurrently.

This is a named `record_audit_fingerprint` exception to transactional DDL.
The receipt uses `exception_reason=events-function-index`; no rollback copy
is needed because no table, column, or ledger row is rewritten or removed.
The empty table/count maps explicitly describe a schema-only operation.
Catalog validation and receipt persistence fail closed. A retry fills any
missing receipt before returning, including after a build completed but its
receipt failed. Existing valid indexes do not rebuild on boot.

Boot convergence invokes the helper after the audit table is committed. The
permanent ordered entry invokes the same helper and verifies readiness before
its transactional history membership is recorded. Rehearsal applies that entry
only to the independently verified validation database; fleet preflight uses
the real boot sequence on disposable copies. Workstation production connections
cannot build or apply this index. Production receives it through the serving
release's boot, and acceptance measures both full-history diagnostics there.
