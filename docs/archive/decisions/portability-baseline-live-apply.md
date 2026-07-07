# `portability_baseline_2026_04` applied to the live DB post-YOK-1476

## Context

YOK-1476 landed the portable-DDL baseline (no `AUTOINCREMENT`, no
`DEFAULT (strftime(..., 'now'))`, no `DEFAULT (datetime('now'))`) across
`runtime/api/`. Task 1 shipped a one-shot migration at
`runtime/api/domain/migrations/portability_baseline_2026_04.py` that rebuilds
every affected core table under `GovernedMigration` (pre-flight backup, FK
integrity, row-count verification, auto-rollback on any deviation).

Task 1 AC-6 required running the migration against a *temp copy* of
`data/yoke.db` to verify it was safe, and the epic's "Watch Out For" note
pre-approved running it against the live DB ("leave `migration_audit` alone
in Task 001; it's an append-only audit log"). Task 6 then deleted the
migration module per CLAUDE.md's "delete completed migrations" rule.

The migration was **never applied to the live DB at
`/Users/dev/yoke/data/yoke.db`.** Task 6 deleted the module before
its "applied everywhere it needs to run" precondition was met. Production
kept running fine because every INSERT call site binds `iso8601_now()`
explicitly — the DB-level DEFAULT was unused-but-harmless. The drift would
have bitten only at Postgres cutover, which is precisely the failure mode
YOK-1476 existed to prevent.

## Decision

Recover the migration module from git history (`cade2d9d7~1`), run it
against the live DB, and discard the recovered copy. No ticket, no
YOK-1476 amendment.

## Outcome

- **Applied:** 2026-04-22T11:08:23Z — 2026-04-22T11:08:27Z (duration 5919ms).
- **Rebuilt:** 35 tables — `capability_secrets`, `capability_templates`,
  `caveat_dispositions`, `deployment_flows`, `deployment_preview_environments`,
  `deployment_run_items`, `deployment_run_qa`, `deployment_runs`, `designs`,
  `environments`, `ephemeral_environments`, `epic_dispatch_chains`,
  `epic_progress_notes`, `epic_task_files`, `epic_tasks`, `events`,
  `events_envelope_backup`, `item_dependencies`, `item_sections`, `merge_locks`,
  `ouroboros_entries`, `project_capabilities`, Project Structure tables, `projects`,
  `qa_artifacts`, `qa_requirements`, `qa_runs`, `release_entries`,
  `severity_config`, `shepherd_verdicts`, `sites`, `work_claims`,
  `wrapup_reports`.
- **Intentionally excluded:** `migration_audit` — the harness writes into
  this table as part of its own lifecycle, so rebuilding it during a governed
  migration would mutate the very counter the harness is verifying. Its
  `AUTOINCREMENT` is deferred to a later migration that runs outside the
  governed harness. Documented inline in the migration module's
  `EXCLUDED_TABLES` constant.
- **Row counts:** every rebuilt table preserved exactly (see
  `migration_audit` row for this run — `expected_deltas` all `0`,
  `pre_row_counts == post_row_counts`). `events: 314919 → 314919`,
  `qa_runs: 4402 → 4402`, `ouroboros_entries: 3282 → 3282`, etc.
- **Backup preserved:**
  `data/backups/yoke.db.20260422-110821.pre-migration-portability_baseline_2026_04.sqlite3`.
- **Post-state residue:** repo-wide grep for banned patterns in
  `sqlite_master` returns **1** hit (the intentional `migration_audit`
  exclusion); 0 hits elsewhere.
- **Full-suite pytest:** `python3 -m pytest runtime/api/` → **6020 passed /
  0 failed / 0 errors** — no regressions from the live-DB rewrite.

## Consequences

- **Cutover-ready:** the live DB's DDL now matches the portable baseline in
  `runtime/api/domain/schema.py`. A future Postgres cutover no longer has to
  discover and rewrite SQLite-specific DDL mid-migration.
- **`migration_audit` remains a known exception.** A later one-shot
  migration (running outside `GovernedMigration`, since it'd be rebuilding
  the audit table) will clean this up. Not blocking; safe to drop when
  convenient. This is the one table the Postgres cutover script will still
  need to hand-adjust.
- **Process gap captured.** `GovernedMigration`-authored one-shots that ship
  under CLAUDE.md's "delete completed migrations" rule need an explicit
  "apply to everywhere it needs to run" checklist item before deletion.
  Adding that check to shepherd/architect guidance is a follow-up improvement
  worth considering; not actioned here.
- **Follow-up tickets unchanged.** YOK-1480 (test-fixture VIEW
  `json_extract` annotation) and YOK-1481 (runtime `datetime('now', …)`
  WHERE-clause sweep — "Postgres-cutover epic 2") remain open and unaffected
  by this apply.

## Links

- Epic: [YOK-1476](https://github.com/upyoke/yoke/issues/3484)
- Source commit for the recovered module:
  `cade2d9d7~1:runtime/api/domain/migrations/portability_baseline_2026_04.py`
  (YOK-1476 close; the commit `cade2d9d7` is the deletion).
- Audit row: `migration_audit` where `migration_name =
  'portability_baseline_2026_04'`, status `completed`.
