# Retire the legacy session-report store

## Decision

Remove the inactive session-report storage and its public write/read surfaces.
Session continuity remains in item Progress Logs and Ouroboros field-notes;
there is no generated report file or second persistence path.

## Evidence

- The authoritative pre-apply count was 59 rows.
- The governed validation rehearsal completed at
  `2026-08-02T18:49:37Z` against a restored disposable copy containing those
  59 rows.
- The authoritative governed apply completed at
  `2026-08-02T18:53:28Z` with `state=completed` and a rollback backup recorded
  by `migration_audit`.
- The post-apply authority has no `wrapup_reports` table, while
  `ouroboros_entries` remains present.
- The focused regression suite passed 470 tests, and Ruff reported no issues
  in the changed Python files.

## Consequences

The old report rows are intentionally gone. Existing session-end guidance
records durable continuity through the item Progress Log and field-notes, so
future sessions retain the useful handoff information without maintaining a
dedicated report table, handlers, adapters, or generated artifacts.
