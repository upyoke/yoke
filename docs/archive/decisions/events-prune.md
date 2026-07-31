---
title: events-prune — retention-only exception pathway
incident_type: durable-exception
owning-helper: packages/yoke-core/src/yoke_core/domain/events_prune.py::cmd_prune
exception-name: events-prune
matching-pattern: docs/archive/decisions/events-schema-rebuild-deletion.md
---

# `events-prune` exception pathway

## What this records

`cmd_prune` in `packages/yoke-core/src/yoke_core/domain/events_prune.py` is a durable
retention-only destructive maintenance helper against the `events`
table and the `session_tool_calls` rolling-state table.  It deletes
events rows by severity/age (DEBUG > 1d, INFO > 30d,
WARN > 90d; STATUS never pruned) and `session_tool_calls` rows older
than `SESSION_TOOL_CALLS_RETENTION_DAYS` (7d — the table's readers are
the session-end orphan sweep and the minutes-lookback PreToolUse lint
guardrails, so week-old rows are inert), then emits a
`migration_audit` fingerprint under
`migration_name='events-prune'` via
`record_audit_fingerprint` so the operation is discoverable alongside
governed migrations. It also removes explicitly obsolete event names
listed in `PURGED_EVENT_NAMES`; rows referenced by immutable path-audit
records are retained.

## Why it is an exception rather than a `GovernedMigration` caller

The governed `GovernedMigration` context manager expects a zero-delta
or declared-delta verification contract.  `cmd_prune` has **non-zero
expected delta by design** — the whole point of the call is to delete
rows — and the delta shape depends on real calendar time (DEBUG > 7d
etc) or the finite obsolete-name set. Wrapping it in
`GovernedMigration` is incompatible with that delete-by-selection shape.

The live safety layer is the `db_error_hook` row-count collapse
detector plus the canonical session-start backup.  The audit row
exists so the operation shows up in post-incident audits and so that
retention activity stays visible against the governed-migration
timeline.

## Fail-closed contract (post-I4)

Per G2.P0.I4 (YOK-1483), `record_audit_fingerprint` is fail-closed —
any `sqlite3.Error` it encounters surfaces as `AuditEmissionError`
rather than being swallowed.  `cmd_prune` intentionally **does not**
wrap the audit call in a best-effort try/except: an audit-emission
failure is the signal, and the operator fixes the evidence path before
re-running the idempotent prune.

## Recovery contract

If `cmd_prune` raises `AuditEmissionError` after the retention deletes
have committed, the operator:

1. Inspects the raised error / missing audit evidence.
2. Fixes the emission path (for example DB connectivity, audit-table
   shape, or write constraints). If doctor later flags pairing drift,
   update this decision record separately — missing pairing does not
   block the runtime write path today.
3. Re-runs `python3 -m yoke_core.domain.events_crud prune` — it is
   idempotent: any remaining eligible rows are pruned, and a fresh
   audit row lands.

The operator **must not** attempt to restore rows that were
legitimately eligible for retention deletion.  Those rows were
supposed to be pruned; the failure mode is missing evidence of the
prune, not lost data.
