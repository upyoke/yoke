---
title: purge-synthetic-event-contamination — one-shot synthetic-event purge
incident_type: governed-migration
owning-module: runtime/api/domain/migrations/purge_synthetic_event_contamination.py
ticket: YOK-1704 task 8
---

# `purge_synthetic_event_contamination` decision record

## What this records

The governed migration module
`runtime/api/domain/migrations/purge_synthetic_event_contamination.py`
deletes synthetic / test-derived rows from the canonical events
ledger. The residue accumulated before the three-layer writer
isolation contract landed (autouse `YOKE_EVENTS_ISOLATION=1` for
`runtime/api/` and `runtime/harness/`, the sqlite-authorizer
canonical-write guard in `db_helpers.connect`, and the
`isolation_gate_blocks` gate in `events_isolation.py`).

Task 7's regression test
(`runtime/api/test_events_synthetic_writer_isolation.py`) pins those
layers so no new pytest run can re-contaminate the ledger. This task
deletes the historical residue.

## DB claim shape

- `model`: `primary`
- `mutation_intent`: `apply`
- `compatibility_class`: `pre_merge_safe`
- `migration_strategy`: `hard_cutover`

The matrix entry `founder_cutover + hard_cutover` allows the apply
without a justification string.

## Exact predicates used to identify synthetic rows

Two predicate families are deleted. Both run on the `events` table.

### Narrow predicate (HC-events-synthetic-contamination)

```sql
session_id LIKE 'test-%'
   OR session_id LIKE 'pytest-%'
   OR session_id LIKE 'fixture-%'
   OR service LIKE '%-test'
   OR service LIKE 'test-%'
```

### Broad predicate (HC-synthetic-event-contamination)

```sql
(session_id LIKE 'sess-%' OR session_id = 'dup')
AND (anomaly_flags IS NULL
     OR anomaly_flags NOT LIKE '%synthetic_smoke%')
```

The `anomaly_flags NOT LIKE '%synthetic_smoke%'` clause preserves
intentionally-retained smoke lineage so the doctor HC never reports
documented exceptions as contamination.

## Total row count matched (Task 07 evidence packet)

Observed against the canonical yoke.db on 2026-05-16 just before
authoring this task:

| Predicate family | Rows |
|------------------|-----:|
| Narrow (`HC-events-synthetic-contamination`)         | 5,574  |
| Broad (`HC-synthetic-event-contamination`)           | 14,623 |
| **Union total**                                      | **~20,197** |

The narrow and broad families are disjoint by construction (narrow
matches `test-` / `pytest-` / `fixture-` prefixes and `*-test` / `test-*`
service tags; broad matches `sess-` prefix and the literal `dup`
session_id). Today's run shows narrow=5,574 and broad=14,623 with no
overlap.

## Sentinel / backfill exclusions

Three session_ids look synthetic but are legitimate historical data
and are NOT deleted. They match the
`SYNTHETIC_SENTINEL_SESSIONS` tuple in
`runtime/api/engines/doctor_hc_db_catalog.py`:

| `session_id` | Why preserved |
|---|---|
| `unknown` | Historical pre-session-attribution rows. Doctor surfaces these separately as "historical sentinel/backfill rows". |
| `migration-zero-legacy` | Migration-zero apply lineage; matches `migration_audit` evidence. |
| `status-events-backfill` | One-shot status-event backfill lineage; required for historical telemetry continuity. |

The doctor HC `hc_synthetic_event_contamination` already separates
these rows in its PASS detail line:
`historical sentinel/backfill rows: N` — they are reported, not
flagged.

Rows tagged `anomaly_flags LIKE '%synthetic_smoke%'` are also
preserved (intentionally-retained smoke lineage); the broad predicate
excludes them explicitly. The current canonical DB carries 0
`synthetic_smoke`-tagged rows but the predicate is written to be
durable when intentional smoke rows are introduced.

## Sample rows per predicate family

### Narrow predicate (5 samples)

| id     | event_name           | session_id   | service | source_type | created_at           |
|-------:|----------------------|--------------|---------|-------------|----------------------|
| 122809 | SessionOffered       | test-sess-1  | cli     | backend     | 2026-04-03 18:59:03  |
| 122810 | SessionRegistered    | test-sess-1  | cli     | backend     | 2026-04-03 18:59:03  |
| 122811 | WorkClaimed          | test-sess-1  | cli     | backend     | 2026-04-03 18:59:03  |
| 122812 | SessionOffered       | test-sess-hb | cli     | backend     | 2026-04-03 18:59:03  |
| 972291 | YokeFunctionCalled | test-session | cli     | backend     | 2026-05-13T15:09:04Z |

### Broad predicate (5 samples)

| id     | event_name        | session_id | service | source_type | created_at           |
|-------:|-------------------|------------|---------|-------------|----------------------|
| 122713 | SessionRegistered | sess-1     | cli     | backend     | 2026-04-03 18:58:36  |
| 122714 | SessionRegistered | sess-1     | cli     | backend     | 2026-04-03 18:58:37  |
| 122716 | SessionRegistered | dup        | cli     | backend     | 2026-04-03 18:58:37  |
| 209192 | SessionRegistered | dup        | cli     | backend     | 2026-03-31 13:26:43  |
| 209280 | SessionRegistered | dup        | cli     | backend     | 2026-03-31 13:27:41  |

## Time range

- Narrow earliest: `2026-03-16 01:00:47`
- Narrow latest: `2026-05-13T15:09:04Z`
- Broad earliest: `2026-03-31 13:26:43`
- Broad latest: `2026-05-14T12:13:02Z`

All flagged rows pre-date the three-layer isolation contract that
Task 07 verified. No fresh contamination should accumulate after this
slice lands.

## Rollback / recovery instructions

The governed-runner contract takes a pre-apply backup before
mutating the authoritative DB. The backup path is recorded on the
`migration_audit` row in the `backup_path` column:

```bash
python3 -m runtime.api.cli.db_router query \
  "SELECT id, migration_name, state, backup_path FROM migration_audit \
   WHERE migration_name='purge_synthetic_event_contamination' \
   ORDER BY id DESC LIMIT 1"
```

To restore from the backup, the operator shuts down any live writers
against the canonical DB and runs:

```bash
python3 -m runtime.api.domain.migration_harness restore <db-path> <backup-path>
```

The migration is idempotent — re-running `apply()` after a partial
restore is safe. `invariants(conn)` post-check raises an
`AssertionError` if any matching row remains, so a botched restore
surfaces loudly rather than silently leaving residue.

## Same-slice deletion

Per CLAUDE.md `## Governed DB Mutation`, single-install topologies
delete the module file in the same slice as the live-apply, once
`migration_audit.state='completed'` lands on the authoritative DB.
Yoke is single-install, so the module and its sibling test file are
deleted in the same commit as the live-apply evidence.

The decision record at this path is the durable record of the
operation; git history preserves the deleted module.
