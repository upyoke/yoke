---
name: resync
description: Detect and repair drift between local backlog items and their GitHub issues. Default mode is detect-only (read-only); use --fix for auto-repair.
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "[--fix]"
---


<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

# /yoke resync [--fix]

Compare authoritative backlog state with linked GitHub issues: title, stage,
priority, workflow, frozen/blocked labels and body. Requires the source-dev/admin
runtime plus installed/authenticated `gh`.

## Phase map

| Phase | Action |
|---|---|
| Detect or repair | Run below |
| Report | Show the complete captured result |

## Run

Default detection makes zero GitHub writes. `--fix` repairs fixable drift.

```sh
yoke resync
yoke resync --fix
```

Capture the full drift report. Read `yoke resync --help` for command depth.
Show scanned/mismatch totals, each field's local/GitHub values, actual repairs
and anything requiring judgment. Report in-sync only when no drift was found;
in detect-only mode list mismatches and suggest `/yoke resync --fix`. After
repair, identify fixed and unrepairable items; never imply an unperformed repair.

Frozen and blocked labels follow `items.frozen`/`items.blocked` through existing
flag sync. Blocked drift is `HC-blocked-label-drift`; clearing the flag removes
the legacy blocked-stage indicator. Check periodically or after bulk changes.
