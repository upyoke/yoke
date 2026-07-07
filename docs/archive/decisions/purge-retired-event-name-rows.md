---
title: purge-retired-event-name-rows — one-shot historical cleanup of retired ToolCall*/Session* names
incident_type: durable-exception
owning-helper: runtime/api/domain/migrations/purge_retired_event_name_rows.py::run
exception-name: purge-retired-event-name-rows
matching-pattern: docs/archive/decisions/events-prune.md
retired-without-apply: false
---

# `purge-retired-event-name-rows` exception pathway

## What this records

A one-shot retention-only migration in
`runtime/api/domain/migrations/purge_retired_event_name_rows.py` that
DELETEs every row in `events` whose `event_name` joins
`event_registry.status='retired'`. After deletion it runs
`PRAGMA wal_checkpoint(TRUNCATE)` and `VACUUM`, then emits a
`migration_audit` fingerprint under
`migration_name='purge-retired-event-name-rows'` via
`record_audit_fingerprint` so the operation is discoverable alongside
governed migrations.

At authoring time on `data/yoke.db` the live retired-name footprint
was ~260k rows across 25 distinct `event_registry.status='retired'`
names (the six largest — `ToolCallCompleted`, `ToolCallStarted`,
`ToolCallDenied`, `SessionRegistered`, `ToolCallFailed`, `SessionEnded`
— accounted for ~254k of those). All retired producers stopped emitting
in April 2026; what remained was purely pre-rename historical telemetry.

## Foreign-key fences (preserved retired-name rows)

Three tables hold `FOREIGN KEY (recorded_event_id) REFERENCES events(event_id)`:
`path_moves`, `path_context_values`, and `path_integrity_repairs`. Any
retired-name event that is still referenced by a row in those tables is
**preserved** by this migration — the DELETE predicate adds
`AND event_id NOT IN (SELECT recorded_event_id FROM <table>)` for each
referencing table so the FK is never violated, and the migration
emits a per-name "preserved (FK-pinned)" line plus an
audit-row description suffix when any rows survive.

At first live apply against `data/yoke.db` this fence preserved 4
`PathContextMigrated` rows referenced by ~1520 `path_context_values`
rows. Those rows are immutable audit records of historical
`PathContextMigrated` runs; removing them would break referential
integrity. Deleting the path_context_values rows themselves is out of
scope for a retention-only cleanup. The fence behavior is exercised by
the migration's sibling test (`test_fk_pinned_retired_rows_are_preserved`,
`test_dry_run_lists_fk_pinned`) prior to module deletion.

## Why it is an exception rather than a `GovernedMigration` caller

The governed `GovernedMigration` context manager expects a zero-delta
or declared-delta verification contract. This migration has **non-zero
expected delta by design** — the whole point is to delete rows — and the
exact delta depends on whatever retired-name historical rows happen to
sit in the events table at apply time. Wrapping in `GovernedMigration`
is incompatible with the delete-by-name shape, exactly as
`runtime/api/domain/events_prune.py` (whose paired record at
[events-prune.md](events-prune.md) was the model) is incompatible for
delete-by-age.

The live safety layer is the `db_error_hook` row-count collapse
detector plus the canonical session-start backup. The audit row exists
so the operation shows up in post-incident audits and so retention
activity stays visible against the governed-migration timeline.

## Fail-closed contract

`record_audit_fingerprint` is fail-closed: any `sqlite3.Error` it
encounters surfaces as `AuditEmissionError` rather than being
swallowed. This module intentionally **does not** wrap the audit call
in a best-effort try/except. An audit-emission failure is the signal,
and the operator fixes the evidence path before re-running the
idempotent migration. The DELETE has already committed by that point,
so recovery does NOT involve restoring rows — those rows were
deliberately eligible for retention deletion.

## Idempotency

A second invocation against the same DB is a no-op: the second-pass
`SELECT COUNT(*) ... WHERE event_name IN (... status='retired')`
returns 0, the module prints `"No retired-name rows present; skipping
DELETE/VACUUM."`, and no new audit row is written. This is tested
explicitly in
`runtime/api/domain/migrations/test_purge_retired_event_name_rows.py::test_idempotent_second_run_is_noop`.

## Live apply and module deletion timing

Yoke declares a single-authoritative `primary` install. Per the
`AGENTS.md > ## Code Conventions` rule **"delete completed migrations
only after applied-everywhere evidence"** and the
`HC-stranded-migration-module` backstop, the migration module and its
paired test are deleted from the tree in the same slice that records a
`state='completed'` audit row on the authoritative DB. The decision
record persists in `docs/archive/decisions/` after the module is
deleted; the audit row is the durable evidence the cleanup happened.

## Companion regression guard

The drop-once nature of this migration only addresses historical rows.
A future producer could in principle re-introduce the same retired
names. The companion guard
`runtime/api/domain/events_retired_name_guard.py` is wired into the
two sanctioned insertion paths — `runtime.api.domain.events.emit_event`
and `runtime.api.domain.events_writes.cmd_insert` — to refuse any
`event_registry.status='retired'` name before the row is written. When
`event_registry` contains a direct active `Harness{event_name}`
successor, the refusal names it; otherwise the message points callers
back to the registry instead of inventing a replacement. The guard makes
this a one-shot cleanup, not a recurring sweep.
