# Write-Time Isolation & Querying Guidance

Cross-link back from [event-contract.md](../event-contract.md) for the envelope structure, registry rules, and reserved-field conventions that surround these isolation rules.

## The Primary Contract: Write-Time Isolation

The live `events` ledger is production telemetry. Synthetic test rows **must not** land in it under any normal workflow. The write-time isolation contract is enforced by the native emitter (`yoke_core.domain.events.emit_event`) and the CLI owner (`yoke_core.domain.emit_event`). Both honor the same environment variables:

| Env var | Meaning |
|---|---|
| `YOKE_EVENTS_ISOLATION=1` | Refuse any live-ledger write unless an escape hatch applies. |
| `YOKE_PG_DSN=... dbname=yoke_test_*` | Route emissions to an explicit Postgres test DB. Escape hatch. |
| `YOKE_DB=/path/to/temp.db` | Legacy file-backed tests only: route emissions to an explicit test DB path. Escape hatch. |
| `YOKE_EVENTS_CAPTURE=1` + `YOKE_EVENTS_FILE=/path/to.ndjson` | Divert emissions to an NDJSON capture file. Escape hatch. |
| `YOKE_EVENTS_CAPTURE=1` alone (no file) | **Refused** — declared capture intent with no sink is never allowed to fall through to the live ledger. |

**Escape hatches under `YOKE_EVENTS_ISOLATION=1`:**

1. **Explicit test DB authority.** On Postgres, emissions proceed when `YOKE_PG_DSN` targets a database whose name carries the shared `yoke_test_` prefix. Legacy file-backed tests may still use an explicit `YOKE_DB` test path.
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

> Previously the only guardrail was a query-time filter. It is preserved here for historical ledger reads (rows emitted before write-time isolation landed) and for forensics. For new code, prefer the write-time contract above.

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

**Real production sessions** may use several truthful shapes depending on the surface. Claude Code startup sessions follow the `claude-code-YYYYMMDDTHHMMSSZ-NNNNN` pattern, `/yoke do` offer sessions keep their Yoke-owned `{executor}-{timestamp}` ids, and Codex shell/manual hook paths may use the live `CODEX_THREAD_ID` UUID directly (for example `019d62e0-2c92-7a03-8d99-b18206cfa7e7`). Treat all of those as valid production identities when correlating events.

## Synthetic-Row Cleanup Guidance

If `HC-synthetic-event-contamination` reports pre-existing contamination from before write-time isolation landed, the safe cleanup pattern is:

1. **Inspect first.** Never bulk-delete without a dry run:
   ```sh
	   yoke db read \
     "SELECT event_name, COUNT(*) FROM events \
     WHERE (session_id LIKE 'test-%' OR session_id LIKE 'sess-%' OR session_id = 'dup') \
     AND (anomaly_flags IS NULL OR anomaly_flags NOT LIKE '%synthetic_smoke%') \
     GROUP BY event_name ORDER BY 2 DESC"
   ```
2. **Preserve sentinel lineage.** Rows with `session_id IN ('unknown', 'migration-zero-legacy', 'status-events-backfill')` are legitimate historical data — never delete them, even though they look unusual.
3. **Scope the delete narrowly.** Use the same contamination predicate; confirm the row count matches step 1; back up the DB before executing. Direct `DELETE FROM events ...` is an escape hatch — route it through an audited migration rather than ad hoc SQL.
4. **Do not touch `synthetic_smoke`-tagged rows.** They are intentional residents.

Write-time isolation prevents new contamination, so cleanup should be a one-time operation against pre-existing rows; no recurring cleanup cron is needed.

## Sentinel Session IDs

Historical migration and backfill operations used sentinel `session_id` values. These rows are legitimate historical data but should be understood in context:

| Sentinel | Row count | Origin |
|----------|-----------|--------|
| `unknown` | ~5,368 | Early `python3 -m yoke_core.domain.observe` rows before session ID resolution was implemented |
| `migration-zero-legacy` | ~2,377 | `TaskStatusChanged` rows created by the legacy task-history migration from `epic_task_history` |
| `status-events-backfill` | ~1,202 | `ItemStatusChanged` / `TaskStatusChanged` rows backfilled from historical status data |
| UUID-format | ~44,000+ | Real `python3 -m yoke_core.domain.observe` sessions before `claude-code-*` format was adopted |

**For production-only lifecycle queries** (session/claim events), filter to `claude-code-%`:

```sql
WHERE session_id LIKE 'claude-code-%'
```

**For all-time analysis** (including historical tool-call telemetry), UUID-format session IDs are real production data and should be included.

## Historical Rows with Null item_id

Some event families have rows where `item_id` is null. This is expected in these cases:

| Event | When item_id is null | Reason |
|-------|---------------------|--------|
| `NextActionChosen` | Actions: `feed`, `escalate`, `wait`, `strategize` | These actions do not target a specific work unit |
| `HarnessSessionOffered` | Always | Session offers precede item selection |
| `HarnessSessionStarted` / `HarnessSessionEnded` | Always | Session-level events, not item-level |
| `FrontierComputed` | Always | Frontier is a project-wide computation |
| `HarnessToolCallStarted` / `HarnessToolCallCompleted` / `HarnessToolCallFailed` / `HarnessToolCallStructuredExit` / `HarnessToolCallDenied` | Main-session calls with multiple in-flight items or shared-main overlap | Execution context resolution is still best-effort for non-worktree sessions |

## Normalization Scripts

- the events-backfill migration -- Backfills `tool_use_id`, `turn_id`, `hook_event_name` from envelope/event data, and normalizes prefixed or bare `item_id` values to canonical numeric text. Idempotent and safe to re-run. Batch-processed for safety.
- the events-correlation migration -- Adds the correlation columns (`turn_id`, `hook_event_name`) to the events table and refreshes any legacy duplicate-session schema. Prerequisite for backfill; called automatically by `migrate-events-backfill`.
