# The hook client's wall-time report is a keyed, bounded, capped probe

## What happened

A hook client measures its own wall time — the span the harness actually
waits, which the server cannot see — and reports it after the hook returns.
The first version of the server side found the dispatch row to complete by
matching the client's correlation id against the event envelope:

```sql
SELECT ... FROM events
WHERE event_name = 'HookDispatchTelemetry'
  AND created_at >= <now - 30 days>
  AND envelope LIKE '%<client id>%'
ORDER BY created_at DESC LIMIT 8
```

`envelope` is JSON text with no index over its contents, so this reads and
matches every telemetry row in a thirty-day window. On a production ledger of
~3.4M rows / 4.6 GB that is 1.5–2.5 minutes per report. Reports arrive about
twice a second fleet-wide, and a report whose row has not landed yet — the
ordinary case for a deferred observation — pays the full scan and finds
nothing. Thirty-one to thirty-nine concurrent scans accumulated, nine updates
queued behind a twenty-two-minute transaction, and 41 of 46 connections went
busy. Every relayed function call took 5–66 seconds, `/v1/health` timed out
through the platform, dashboards rendered empty, and launches and the fleet
watcher failed with `https_transport_failed` for thirty-five minutes on
2026-09-04.

## What replaced it

**The correlation key gets its own column.** `events.client_timing_id` is
written at emit time from the telemetry context and matched by equality. The
supporting index is partial — `WHERE client_timing_id IS NOT NULL` — and the
completing update clears the column, so the index holds only the reports
actually in flight rather than growing with the ledger.

**The window is minutes, not days.** Fifteen, against a resident that flushes
its observation queue every two seconds. The bound is deliberate redundancy:
it keeps a miss cheap on a database whose converge has not yet built the
index, and it keeps the query bounded if the index is ever dropped.

**A miss costs one probe.** Not finding a row is the expected outcome when
the dispatch has not been persisted yet, so it has to be the cheapest path,
not the most expensive one.

**No row lock is held across a read.** Each report commits its lookup before
opening the update, so a slow statement can never sit on a row lock while
another statement is still reading.

**The connection caps every statement.** Hook-observation database sessions
set `statement_timeout` (`hook_observation_db_session`). Telemetry is
best-effort evidence sharing a pool with every relayed call; a statement that
overruns there is refused and retried, which is loud and local, rather than
silently holding a connection.

## Why the ban is enforced rather than remembered

`HC-events-envelope-like-scan` refuses executable SQL matching
`events.envelope` with LIKE. Its allowlist admits a reader only with the
indexed key that bounds it named in the entry, and request-path code does not
qualify however narrow the bound: an operator-invoked audit absorbs a slow
scan on one connection, and a hook running on every tool call does not. The
scan reads executable string literals only, so prose teaching the rule — this
file, the check's own docstring, the denial message — is never itself a
violation.

## The emergency mitigation this retired

While the incident was live, the production role `yoke_tenant_owner` was
given a blanket `statement_timeout` and the offending build was rolled back.
A role-wide cap is the wrong shape for the long term: it silently aborts
legitimate long work, including the boot converge's own index builds. The
per-session cap on the hook-observation paths is the version that belongs in
code, and the role setting was reset in the change that shipped it.
