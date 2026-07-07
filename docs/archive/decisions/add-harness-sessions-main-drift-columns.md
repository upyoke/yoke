---
title: add-harness-sessions-main-drift-columns — stranded-module retire
incident_type: governed-migration-retire
owning-module: runtime/api/domain/migrations/add_harness_sessions_main_drift_columns.py
ticket: YOK-1704 task 11
retired-without-apply: true
---

# `add_harness_sessions_main_drift_columns` decision record

## What this records

Same-slice retirement of the governed migration module
`runtime/api/domain/migrations/add_harness_sessions_main_drift_columns.py`.
The module added two nullable advisory columns to `harness_sessions`:

- `last_seen_main_sha` (`TEXT DEFAULT NULL`)
- `last_drift_check_at` (`TEXT DEFAULT NULL`)

## Frontmatter convention note

CLAUDE.md `## Governed DB Mutation` documents one canonical frontmatter
marker for retire-flow decision records: `retired-without-apply: true`.
This module did historically apply (single-install `primary`
`migration_audit` row records `state='completed'`), but the frontmatter
key is read as the canonical retire marker — "this record retires the
module" — not as a literal claim that the apply never happened. The
precedent `docs/archive/decisions/events-schema-rebuild-deletion.md`
applies the same convention to a module that had previously executed
its cleanup branch in the field. No competing frontmatter
(`retired-after-apply`, etc.) exists anywhere in the repo today, so
this record follows the existing single convention.

## Authoritative apply evidence (AC-1 [READ-ONLY])

Captured against the canonical Yoke `yoke.db` on 2026-05-16:

```text
$ python3 -m runtime.api.cli.db_router query \
    "SELECT id, migration_name, model_name, state, project_id, completed_at \
     FROM migration_audit WHERE id = 37"
37|add_harness_sessions_main_drift_columns|primary|completed|yoke|2026-05-03T23:44:02Z
```

Single-install topology — Yoke's `primary` authoritative DB is the
only governed install for this model. Per CLAUDE.md
`## Governed DB Mutation`, single-install completed modules retire in
the same slice as the live-apply once `migration_audit.state='completed'`
lands.

## Same-slice deletion

This task deletes
`runtime/api/domain/migrations/add_harness_sessions_main_drift_columns.py`
in the same commit that lands this decision record. No companion test
file was observed during refine
(`runtime/api/domain/test_add_harness_sessions_main_drift_columns.py`
does not exist); none is created by this task per the parent spec's
AC-24.

The columns themselves stay on `harness_sessions` — they are live
schema, not part of this retirement.

## HC-stranded-migration-module evidence

The doctor health check
`runtime/api/engines/doctor_hc_stranded_migrations.py` enumerates module
files under `runtime/api/domain/migrations/` and joins against
`migration_audit.state='completed'`. After this slice lands, the
module name no longer appears in the directory listing, so the HC
records `PASS` for this name.

Git history preserves the deleted module body for archaeology.
