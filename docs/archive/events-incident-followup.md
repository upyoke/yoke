# Events Ledger — Incident Follow-up & Maintenance Playbook

**Status:** Active operator guidance (YOK-1252).
**Last incident reference:** 2026-04-03 suspicious collapse in historical
delivery/status telemetry coverage.

This document is the operator-readable closure pass for the events-table
incident that opened with `YOK-1252`. It is structured in four parts:

1. **Inventory** — every current codepath that can delete, rebuild,
   compact, normalize, prune, or bulk-update `events`, and how each is
   governed.
2. **Incident note** — what the 2026-04-03 window actually proves,
   what it does *not* prove, and which preserved artifacts remain.
3. **Recovery playbook** — how to validate or restore the canonical
   `events` ledger from preserved backups without clobbering newer
   post-incident rows.
4. **Discovery commands** — the grep / SQL commands that let a future
   operator rebuild this inventory from a live repo instead of trusting
   this document as a frozen snapshot.

> **Do not trust a stale shortlist.** Re-run the discovery commands in
> §4 before treating this document as authoritative. File a follow-up
> via `/yoke idea` if the live inventory disagrees with what is
> written here.

---

## 1. Inventory of events bulk-write / rewrite / prune paths

Each entry lists: **file**, **function / invocation**, **safety model**,
and **disposition** (`governed` · `exception (documented)` · `retired`).

### 1.1 `yoke/api/domain/events_crud.py::_ensure_events_schema`

- **Invocation:** `cmd_init` (events table bootstrap and column
  migration); called from `schema.cmd_migrate_events_correlation`.
- **Write shape:** creates `events__migrated`, copies rows in, drops
  `events`, renames temp → `events`.
- **Safety model:** in-place `pre_count == post_count` check before
  rename; raises `RuntimeError` on mismatch. On a non-empty existing
  table, a lightweight `migration_audit` fingerprint is emitted
  (`events-schema-rebuild`). The row-count-collapse hook
  (`runtime.api.domain.db_error_hook.check_row_count_collapse`) is the
  runtime safety net (YOK-1296).
- **Disposition:** `exception (documented)` — wrapped inside `cmd_init`
  which predates the `migration_audit` table, so a full
  `GovernedMigration` wrap is not reachable. The in-place row-count
  invariant plus the audit fingerprint is the safety contract.

### 1.2 `yoke/api/domain/events_crud.py::cmd_prune`

- **Invocation:** operator command (`events prune` / retention
  maintenance).
- **Write shape:** `DELETE FROM events` by severity + age
  (DEBUG > 7d, INFO > 30d, WARN > 90d). STATUS rows are never pruned.
  Followed by `PRAGMA wal_checkpoint(TRUNCATE)` and `VACUUM` when any
  rows were deleted.
- **Safety model:** bounded by design (severity × age). `migration_audit`
  fingerprint (`events-prune`) is emitted after a real (non-dry-run)
  prune with pre/post row counts and pruned-by-severity detail.
- **Disposition:** `exception (documented)` — `GovernedMigration` wrap
  is incompatible with the delete-by-age contract (non-zero expected
  delta varies with clock and corpus). The runtime safety layer is
  `check_row_count_collapse` and the audit fingerprint; the bounded
  retention policy is the correctness contract.

### 1.3 `yoke/api/domain/schema.py::cmd_migrate_events_backfill`

- **Invocation:** `schema-db migrate-events-backfill` (YOK-1322
  task 010 one-shot; idempotent via WHERE clauses).
- **Write shape:** batched `DELETE` (dedupe tool-call rows) plus
  multiple bulk `UPDATE` passes that backfill correlation columns and
  normalize item / task refs.
- **Safety model:** wrapped in `GovernedMigration` with
  `expected_deltas={"events": -dedupe_count}`. The harness takes a
  pre-flight backup, captures baseline row counts, and auto-rolls back
  on deviation or exception.
- **Disposition:** `governed` (YOK-1252).

### 1.4 `yoke/api/domain/schema.py::cmd_migrate_events_correlation`

- **Invocation:** `schema-db migrate-events-correlation`; also called
  transparently from `cmd_migrate_events_backfill`.
- **Write shape:** `ALTER TABLE events ADD COLUMN` (idempotent via
  `_add_column_if_not_exists`); no row-level writes.
- **Safety model:** additive schema-only; zero row-count delta. May
  indirectly trigger `_ensure_events_schema` rebuild (see §1.1).
- **Disposition:** `exception (documented)` — additive DDL is safe and
  does not benefit from a harness wrap. The rebuild path it may trigger
  *is* governed through §1.1.

### 1.5 `yoke/api/tools/backfill_lifetime_activity.py::migrate_legacy_backfill_rows`

- **Invocation:** `python3 -m runtime.api.tools.backfill_lifetime_activity --migrate-existing`
  (YOK-1381 one-shot rewrite of legacy `activity_backfill` rows).
- **Write shape:** in-place `UPDATE events` in a single transaction;
  zero row-count delta.
- **Safety model:** single transaction with rollback-on-error.
  `migration_audit` fingerprint
  (`events-legacy-backfill-rewrite`) is emitted after a successful
  rewrite, carrying `pre_count == post_count` invariant.
- **Disposition:** `exception (documented)` — zero-delta UPDATE-only
  rewrite, GovernedMigration would add setup cost without changing the
  safety shape.

### 1.6 `.agents/skills/yoke/scripts/repair-events-envelopes.py::repair`

- **Invocation:** called by `events_crud.cmd_init` when malformed
  envelopes are detected; also runnable standalone.
- **Write shape:** back up malformed rows to `events_envelope_backup`,
  rebuild canonical envelopes in place, then `DROP TABLE events; ALTER
  TABLE events_new RENAME TO events` to install the
  `CHECK(envelope IS NULL OR json_valid(envelope))` constraint.
- **Safety model:** row-count invariant (`count_before == count_after`)
  raises `RuntimeError` on mismatch; backup table preserves originals.
  `migration_audit` fingerprint (`events-envelope-repair`) is emitted
  after success.
- **Disposition:** `exception (documented)` — has its own bounded
  backup and row-count verify; wrap-in-GovernedMigration would double
  the backup cost for the same net safety.

### 1.7 `yoke/api/domain/migration_harness.py::GovernedMigration`

- **Role:** the governance kernel itself (YOK-1255). Not a write path —
  it is the contract that rebuild / migration / rewrite paths must
  either use directly or explicitly opt out of with a documented
  exception. `record_audit_fingerprint` is the YOK-1252 lightweight
  emission helper for the exception path.

### 1.8 `yoke/api/domain/db_error_hook.py::check_row_count_collapse`

- **Role:** detection layer, not a write path. Maintains a session
  baseline and emits `DataLossDetected` (severity `FATAL`) when
  critical-table row counts collapse after a DDL command (YOK-1296).
  Covers §1.1 and §1.2 even when the operator bypasses the Python
  surface.

### 1.9 Tests and fixtures that touch `events`

All files under `yoke/api/test_*.py` and `yoke/api/engines/test_*.py`
that `INSERT INTO events` are **test fixtures**, not production write
paths, and are explicitly allowed: they populate ephemeral DBs that are
never merged into the canonical ledger. The HC
`HC-events-synthetic-contamination` watches for test-fixture markers
(`session_id LIKE 'test-%'`, etc.) that leak into a live DB, so an
accidental contamination is surfaced rather than silently ignored.

---

## 2. 2026-04-03 Incident Note

### 2.1 What is now proven

- `yoke/api/domain/migration_harness.py::GovernedMigration` is live
  and reachable; audit fingerprints land in the `migration_audit` table
  with row-count baselines and pre/post deltas (YOK-1255).
- `yoke/api/domain/db_error_hook.py::check_row_count_collapse` emits
  `DataLossDetected` events (FATAL severity) with per-table drop
  percentages and the triggering command (YOK-1296).
- `yoke/api/domain/backup` is the Python-owned backup owner; every
  migration routed through `GovernedMigration` calls it before any
  destructive DDL executes.
- After YOK-1252, every events bulk-write / rewrite / prune path either
  routes through `GovernedMigration` or emits a documented audit
  fingerprint. The `HC-events-destructive-maintenance-audit` doctor
  check fails loudly when a `DataLossDetected` event has no matching
  audit row within ±1 hour.

### 2.2 What the 2026-04-03 window does *not* prove

- The originating command that triggered the 2026-04-03 coverage dip is
  **not reconstructable with certainty**. The backup captured on the
  day after the incident preserves the post-incident state, not the
  exact command. The `DataLossDetected` hook is session-scoped, so if
  the destructive command ran in a session that later exited, the
  per-session baseline file will have been pruned from
  `TMPDIR/yoke-row-baselines/` before post-incident triage began.
- The hypothesis that the collapse was caused by an unwrapped
  `cmd_migrate_events_backfill` run is **consistent with the evidence
  but not conclusive**. After YOK-1252 that path is governed, so the
  question is now academic for future runs; for the historical window
  the best available evidence is the absence of any matching
  `migration_audit` row and the shape of the gap (see
  `HC-events-historical-coverage-collapse`).

### 2.3 Preserved artifacts still available

- `events_envelope_backup` — the envelope-repair backup table. Queryable
  directly for any row that was normalized between YOK-763 and the
  incident window. Use:

  ```bash
  python3 -m runtime.api.cli.db_router query \
    "SELECT issue_kind, COUNT(*) FROM events_envelope_backup GROUP BY 1"
  ```

- `migration_audit` — every governed migration and every YOK-1252
  exception fingerprint. Inspect with:

  ```bash
  python3 -m runtime.api.domain.migration_harness audit-list "$YOKE_DB"
  ```

- Session-backup directory — each `/yoke advance implementation`
  session seed ran `python3 -m runtime.api.domain.backup backup <reason>`.
  The backup log is the authoritative "most recent healthy
  pre-mutation snapshot" for the day the incident fired. Inspect with:

  ```bash
  python3 -m runtime.api.domain.backup list
  python3 -m runtime.api.domain.backup latest
  ```

---

## 3. Recovery and cleanup playbook

Use this playbook when operator evidence suggests an `events` row or
window is missing or suspect. **Never** drop-and-rebuild the canonical
table directly; always stage the recovery against a copy.

### 3.1 Validate first, restore second

1. **Inventory governance** — run

   ```bash
   python3 -m runtime.api.engines.doctor --only events-destructive-maintenance-audit
   python3 -m runtime.api.engines.doctor --only events-historical-coverage-collapse
   python3 -m runtime.api.engines.doctor --only events-synthetic-contamination
   ```

   Any `WARN` here is the starting point. Capture the exact output —
   do not re-run destructive helpers until you know which window you
   are defending.

2. **Locate the backup that covers the window.** The preserved backup
   log lives in `yoke/ouroboros/` and `python3 -m runtime.api.domain.backup list`.
   Pick the newest backup whose timestamp is strictly **before** the
   first suspected gap. Copy it to a staging location — do not
   overwrite `$YOKE_DB`:

   ```bash
   cp "$(python3 -m runtime.api.domain.backup latest)" "$TMPDIR/events-recovery.db"
   ```

3. **Diff the `events` tables** for the window of interest:

   ```bash
   python3 -m runtime.api.cli.db_router query \
     "SELECT event_id, created_at, event_name FROM events \
       WHERE created_at BETWEEN '2026-04-02T00:00:00Z' \
                             AND '2026-04-04T00:00:00Z' \
       ORDER BY created_at"
   YOKE_DB="$TMPDIR/events-recovery.db" \
     python3 -m runtime.api.cli.db_router query \
       "SELECT event_id, created_at, event_name FROM events \
         WHERE created_at BETWEEN '2026-04-02T00:00:00Z' \
                               AND '2026-04-04T00:00:00Z' \
         ORDER BY created_at"
   ```

   The set-difference (what the backup has that the live DB does not)
   is the candidate recovery set.

### 3.2 Restore without clobbering newer rows

The canonical ledger may contain legitimate post-incident rows that
are newer than the window you are trying to recover. Never restore the
whole backup file.

1. Attach both DBs read-only and `INSERT OR IGNORE` only the missing
   event_ids:

   ```bash
   python3 -m runtime.api.cli.db_router query "
     ATTACH DATABASE '$TMPDIR/events-recovery.db' AS bak;
     INSERT OR IGNORE INTO events
       SELECT * FROM bak.events
        WHERE event_id IN (
          /* the candidate set from §3.1 */
        );
     DETACH DATABASE bak;
   "
   ```

   (For multi-statement scripts, use a Python shim — the db_router
   `query` surface accepts a single statement at a time.)

2. Record a `migration_audit` fingerprint so the recovery is
   discoverable:

   ```bash
   python3 -c "
   from runtime.api.domain.migration_harness import record_audit_fingerprint
   record_audit_fingerprint(
     db_path='$YOKE_DB',
     name='events-recovery-from-backup',
     description='Operator recovery of N rows from backup X window Y',
     tables=['events'],
     pre_counts={'events': <pre>},
     post_counts={'events': <post>},
     note='Operator-driven recovery. See yoke/docs/events-incident-followup.md §3.',
   )
   "
   ```

3. Re-run the doctor checks from §3.1. They should now come back clean.

### 3.3 Cleanup: retire stale references

When a recovery is complete, check `events_envelope_backup`,
`ouroboros_entries`, and the Ouroboros log for orphan references to
the incident window. File cleanup via `/yoke idea` — do not silently
delete evidence.

---

## 4. Discovery commands (re-run before trusting this document)

```bash
# 4.1 Every events bulk write/rewrite/delete site in current Python/scripts.
rg -n "DELETE FROM events|DROP TABLE events|ALTER TABLE events|UPDATE events|INSERT INTO events|VACUUM|wal_checkpoint" \
    yoke/api .agents/skills/yoke/scripts

# 4.2 Governance + detection surface (YOK-1255, YOK-1296, YOK-1252).
rg -n "GovernedMigration|record_audit_fingerprint|events__migrated|cmd_prune|repair-events-envelopes|DataLossDetected" \
    yoke/api .agents/skills/yoke/scripts

# 4.3 Existing events-trust HCs in the doctor engine.
rg -n "hc_events_|HC-events-|HC-migration-audit|HC-sqlite-integrity|HC-stray-db" \
    yoke/api/engines/doctor.py

# 4.4 Synthetic / backfill / historical markers visible in the live DB.
python3 -m runtime.api.cli.db_router query \
  "SELECT anomaly_flags, COUNT(*) FROM events \
    WHERE anomaly_flags IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"

python3 -m runtime.api.cli.db_router query \
  "SELECT session_id, service, COUNT(*) FROM events \
    WHERE session_id LIKE 'test-%' OR session_id LIKE 'pytest-%' \
       OR service LIKE 'test-%' OR service LIKE '%-test' \
    GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20"

# 4.5 Audit discoverability for recent destructive maintenance.
python3 -m runtime.api.cli.db_router query \
  "SELECT id, migration_name, state, started_at, \
          substr(COALESCE(exception_reason, failure_reason, ''), 1, 100) AS note \
     FROM migration_audit \
    ORDER BY id DESC LIMIT 20"
```

Each command is deliberately self-contained. If an operator can
rerun §4, they can rebuild the §1 inventory from scratch — so this
document does not need to stay in perfect sync with the live code to
remain useful.
