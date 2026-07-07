---
title: migration_audit_final_shape — hard cutover to §7-portable shape
incident_type: durable-exception
owning-helper: runtime/api/domain/migrations/migration_audit_final_shape.py
exception-name: migration_audit_final_shape
matching-pattern: docs/archive/decisions/portability-baseline-live-apply.md
---

# `migration_audit_final_shape` exception pathway

## What this records

G2.P0.I5 / YOK-1484 collapses the transitional `migration_audit` coexistence
left in place by G2.P0.I3 (YOK-1482). The final shape removes the legacy
`status` column, drops `AUTOINCREMENT` on `id`, promotes `state` to a
NOT-NULL CHECK-constrained status surface, restricts `failure_reason` to
failure-only semantics, and leaves the table aligned with §7
"Portability discipline (binding for every table below)" before the Phase 8
Postgres proof lane. The module name is the evidence key required by the
§7.2 `implementing → reviewing-implementation` evidence gate for YOK-1484.

One-shot module: `runtime/api/domain/migrations/migration_audit_final_shape.py`
(deleted in the same slice after applied-everywhere evidence lands; recovery
is archive-only per §1.5 hard rule #6).

## Why it is an exception rather than a `GovernedMigration` caller

`GovernedMigration` inserts its own tracking row into `migration_audit` at
`__enter__`, then updates it at `__exit__`. Rebuilding `migration_audit`
itself would mutate the very counter the harness is verifying — the pre-flight
row would either disappear mid-rename or need to be hand-copied, and the
post-flight `UPDATE` would race the rename. The portability baseline
(`portability_baseline_2026_04`, YOK-1476) hit the same chicken-and-egg
problem and excluded `migration_audit` from its scope; this slice closes
that carveout through the documented `record_audit_fingerprint`
exception path rather than inventing new harness-reentrancy semantics.

The live safety layer is three-fold: an explicit backup through
`runtime.api.domain.backup` before the rebuild, a row-count invariant that
refuses to commit unless the rebuilt table contains the exact same number
of rows as the original, and a single-transaction envelope around the
CREATE-new / INSERT-SELECT / DROP-old / RENAME sequence so any failure
rolls back before touching the live table name. The audit row exists so the
operation shows up in post-incident audits and so that the cleanup stays
visible against the governed-migration timeline.

## Final shape (post-cutover)

Column set (in declaration order):

| column | type | constraint |
|---|---|---|
| `id` | INTEGER | PRIMARY KEY (no `AUTOINCREMENT`) |
| `migration_name` | TEXT | NOT NULL |
| `description` | TEXT | — |
| `tables_declared` | TEXT | NOT NULL (JSON array) |
| `expected_deltas` | TEXT | NOT NULL (JSON object) |
| `pre_row_counts` | TEXT | NOT NULL (JSON object) |
| `post_row_counts` | TEXT | — |
| `pre_fk_violations` | INTEGER | NOT NULL DEFAULT 0 |
| `post_fk_violations` | INTEGER | — |
| `backup_path` | TEXT | NOT NULL |
| `state` | TEXT | NOT NULL DEFAULT 'planned' + CHECK across the full state vocabulary |
| `failure_reason` | TEXT | — (failure-only semantics; populated when `state` is one of the `*_failed` values) |
| `exception_reason` | TEXT | — (justification when the row was written via `record_audit_fingerprint`) |
| `source_fingerprint` | TEXT | — |
| `rehearsed_at` | TEXT | — |
| `lease_id` | INTEGER | — |
| `test_copy_path` | TEXT | — |
| `baseline_verify_result` | TEXT | — (→ JSONB on Postgres) |
| `author_verify_result` | TEXT | — (→ JSONB on Postgres) |
| `session_id` | TEXT | — |
| `model_name` | TEXT | — |
| `project_id` | TEXT | — |
| `started_at` | TEXT | NOT NULL (UTC ISO-8601) |
| `completed_at` | TEXT | — (UTC ISO-8601) |
| `duration_ms` | INTEGER | — |

`state` CHECK vocabulary:

- success path: `planned`, `test_copy_created`, `test_applied`,
  `test_verified`, `rehearsed`, `backup_created`, `live_applied`,
  `live_verified`, `completed`
- failure branches: `test_copy_failed`, `test_apply_failed`,
  `test_verify_failed`, `backup_failed`, `live_apply_failed`,
  `live_verify_failed`

Dropped: the legacy `status` column and its CHECK over
`('started', 'completed', 'rolled_back', 'failed')`, plus the
`AUTOINCREMENT` clause on `id`.

## Row back-mapping

Every pre-existing row keeps its original `id`, timestamps, counts,
provenance columns, `description`, `backup_path`, `failure_reason`, and
`exception_reason`. The only computed column is `state`:

```
state := COALESCE(NULLIF(state, ''),
    CASE status
        WHEN 'completed'    THEN 'completed'
        WHEN 'applied'      THEN 'completed'
        WHEN 'rolled_back'  THEN 'live_apply_failed'
        WHEN 'failed'       THEN 'test_apply_failed'
        WHEN 'started'      THEN 'planned'
        ELSE 'planned'
    END)
```

Rows written through the I3-era dual-write path already carry a valid
`state`; that value wins. Rows written before I3 carried only `status` and
get the mapping above. The single row present in the live DB at cutover
time (`portability_baseline_2026_04`, `status='completed'`, `state=NULL`)
back-maps to `state='completed'`, matching its actual outcome.

## Fail-closed contract (inherited from I4)

Per G2.P0.I4 (YOK-1483), `record_audit_fingerprint` is fail-closed — any
`sqlite3.Error` it encounters surfaces as `AuditEmissionError` rather than
being swallowed. The cutover module intentionally **does not** wrap the audit
call in a best-effort try/except: an audit-emission failure means the
evidence gate will block the downstream `implementing →
reviewing-implementation` transition until the write path is repaired and
the fingerprint is re-emitted.

## Applied-everywhere evidence

Yoke has a single authoritative install at
`/Users/dev/yoke/data/yoke.db`. "Applied everywhere" therefore
reduces to a single `migration_audit.state='completed'` row with
`migration_name='migration_audit_final_shape'`,
`project_id='yoke'`, and `model_name='primary'`. With that row present,
the module file is deleted in the same slice per CLAUDE.md's "delete
completed migrations only after applied-everywhere evidence" rule. Git
history preserves the implementation.

## Deliberate-stranding statement (per GEN-2-PLAN.md §1.5 hard rule #6)

Installs that still carry the pre-cutover `migration_audit` shape at the
moment I5 lands lose their auto-rebuild path on `cmd_init`: the schema
owner now emits the final shape directly with no transitional upgrade
pass. Recovery is **not supported** through any shipped tool or live doc.
Any reconstruction is archive-only — the operator reads this decision
record and git history to reconstruct the rebuild, then performs whatever
manual recovery their install requires. Yoke ships no SQL playbook, no
companion upgrade tool, and no compatibility shim.

Yoke is in founder-build mode with zero external customers. If any
install still carries the pre-cutover shape at I5 landing, the operator
knows the install and can reconstruct from this record plus git history.
Shipping a recovery tool would be transitional survival machinery for a
transitional caller being deleted — exactly what §1.5 hard rule #6
forbids.

## Links

- Ticket: [YOK-1484](https://github.com/upyoke/yoke/issues/3507)
- Predecessor portability-baseline decision record:
  `docs/archive/decisions/portability-baseline-live-apply.md`
- Predecessor cleanup decision records:
  `docs/archive/decisions/events-schema-rebuild-deletion.md`,
  `docs/archive/decisions/events-prune.md`
- Audit row (after apply): `migration_audit` where
  `migration_name = 'migration_audit_final_shape'`, `state = 'completed'`.
