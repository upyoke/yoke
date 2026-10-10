# Write-Time Isolation & Querying Guidance (internal)

Cross-link back from [event-contract.md](../event-contract.md) for the envelope structure, registry rules, and reserved-field conventions that surround these isolation rules.

## The Primary Contract: Write-Time Isolation

The live `events` ledger is production telemetry. Synthetic test rows **must not** land in it under any normal workflow. The write-time isolation contract is enforced by the native emitter (`yoke_core.domain.events.emit_event`) and the CLI owner (`yoke_core.domain.emit_event`). Both honor the same environment variables:

| Env var | Meaning |
|---|---|
| `YOKE_EVENTS_ISOLATION=1` | Refuse any live-ledger write unless an escape hatch applies. |
| `YOKE_PG_DSN=... dbname=yoke_test_*` | Route emissions to an explicit Postgres test DB. Escape hatch. |
| `YOKE_EVENTS_CAPTURE=1` + `YOKE_EVENTS_FILE=/path/to.ndjson` | Divert emissions to an NDJSON capture file. Escape hatch. |
| `YOKE_EVENTS_CAPTURE=1` alone (no file) | **Refused** — declared capture intent with no sink is never allowed to fall through to the live ledger. |

**Escape hatches under `YOKE_EVENTS_ISOLATION=1`:**

1. **Explicit test DB authority.** On Postgres, emissions proceed when `YOKE_PG_DSN` targets a database whose name carries the shared `yoke_test_` prefix. Legacy file path tokens are inactive compatibility inputs and never establish database authority.
2. **Explicit connection.** Callers that pass `conn=` directly to `events.emit_event(...)` manage their own lifecycle; the gate always honors them.
3. **Capture sink.** `YOKE_EVENTS_CAPTURE=1` + `YOKE_EVENTS_FILE=...` writes NDJSON to the sink.
4. **Intentional smoke lineage.** Emissions tagged with `anomaly_flags="synthetic_smoke"` are an explicit declaration: "this row belongs in the live ledger as a retained smoke-test marker". See "Intentional Smoke Rows" below.

When none of the escape hatches apply, `emit_event` returns a refused result and logs a DEBUG message — emission is dropped silently rather than corrupting the ledger.

**Pytest isolation.** `runtime/api/conftest.py` enables `YOKE_EVENTS_ISOLATION=1` via an autouse fixture for every Yoke API test, so **no new test needs any per-file wiring to stay safe**. Postgres test fixtures repoint `YOKE_PG_DSN` to `yoke_test_*` databases; tests may also pass `conn=` directly. Both are escape hatches recognized by the gate.

## Intentional Smoke Rows (`synthetic_smoke` lineage marker)

Some smoke tests, operator drills, and cross-surface integration probes intentionally emit to the live ledger so that real-world query paths can be validated end-to-end. Those rows must carry the stable machine-readable lineage marker:

```python
from yoke_core.domain.events import emit_event
emit_event(
 "SmokeEmitted",
 event_kind="system",
 event_type="smoke",
 anomaly_flags="synthetic_smoke",
 ...
)
```

Operator queries that want a clean production view **must** exclude tagged rows with:

```sql
WHERE (anomaly_flags IS NULL OR anomaly_flags NOT LIKE '%synthetic_smoke%')
```

The doctor `HC-synthetic-event-contamination` check excludes `synthetic_smoke` rows from its contamination count automatically. That is the default-safe operational query surface.

## Legacy / Defense-in-Depth: Query-Time Filter

> Write-time isolation is the primary contract. For forensic queries, the filter below excludes the listed synthetic session patterns.

```sql
-- Legacy query-time filter for historical rows
WHERE session_id NOT LIKE 'test-%'
 AND session_id NOT LIKE 'sess-%'
 AND session_id <> 'dup'
```

**Legacy test-derived session ID patterns:**

| Pattern | Origin |
|---------|--------|
| `test-*` | Test suites (e.g., `test-session-001`, `test-sess-claim`, `test-7534-*`) |
| `sess-*` | Test suites (e.g., `sess-1`, `sess-A`, `sess-race-1`, `sess-envelope-1`) |
| `dup` | Deduplication test fixture |

**Production session identity** comes from the registered harness session. Read `yoke sessions identity --json` before correlating events; never infer an identity from a synthetic fixture pattern.

## Synthetic-Row Cleanup Guidance

When `HC-synthetic-event-contamination` reports contamination:

1. Inspect the affected rows before planning cleanup:
   ```sh
   yoke db read "SELECT event_name, COUNT(*) FROM events WHERE (session_id LIKE 'test-%' OR session_id LIKE 'sess-%' OR session_id = 'dup') AND (anomaly_flags IS NULL OR anomaly_flags NOT LIKE '%synthetic_smoke%') GROUP BY event_name ORDER BY 2 DESC"
   ```
2. Preserve the sentinel lineage listed below and all `synthetic_smoke`-tagged
   rows. Neither is contamination.
3. Scope cleanup to the same contamination predicate and verify the proposed
   row count against the inspection. Use the governed migration path, with its
   required restore point and rehearsal; never execute an ad hoc bulk delete.

Fix the emitting path's isolation before cleanup so it cannot recreate the
contamination. Write-time isolation is the prevention mechanism; a recurring
cleanup job is not a substitute.

## Sentinel Session IDs

The Doctor reports these legitimate sentinel/backfill rows separately from
synthetic contamination. Preserve them during cleanup:

| Sentinel | Meaning |
|---|---|
| `unknown` | Telemetry whose emitting surface could not resolve a session identity |
| `migration-zero-legacy` | Task-status lineage from the legacy task-history migration |
| `status-events-backfill` | Item/task status lineage reconstructed from stored status data |

Use the registered session identity or an explicit query scope for lifecycle
analysis. UUID-format session IDs are valid production identities; do not
filter them out or restrict production telemetry to one harness's ID prefix.

## Rows with Null `item_id`

`item_id` is optional. Session-level and project-wide events can have no work
item, and tool-call attribution can remain unresolved when no unique item is
available. A null value alone is neither contamination nor a reason to delete
or invent an item reference. For item-scoped analysis, filter to the resolved
item ID; retain unattributed rows for session/project analysis. See the
[event context rules](../event-contract.md#2-execution-context-fields) for attribution.
