---
title: projects.notes — discard decision
date: 2026-04-28
relates_to: context_routing_cutover
---

# projects.notes — discard decision

The retired `projects.notes` column was discarded during the
`context_routing` cutover (Phase 0 I7). This record captures why discard
was the right default rather than absorbing the column into Project
Structure or migrating it to a new home.

## What the column held

`projects.notes` was a free-form text column on the `projects` table. It
had no structured payload contract, no consumers in the live codebase
beyond the generic `projects update <id> notes <value>` CLI passthrough,
and no test surfaces that exercised non-trivial values (tests used it as
a generic "writable field" target).

## Pre-filing live DB check

Before filing YOK-1557 the operator queried both surfaces:

```bash
YOKE_DB=data/yoke.db python3 -m runtime.api.cli.db_router query \
  "SELECT id, notes FROM projects"
```

Both seeded projects (`yoke`, `buzz`) had `notes` empty / NULL on the
authoritative DB and on every accessible install. No live data was at
risk of loss.

## Decision: discard, do not absorb

Three options were considered:

1. **Discard.** Drop the column. No data loss, no consumers to rewire,
   the cleanest restart-from-scratch shape.
2. **Absorb into `context_routing`.** Add a reserved entry_key for
   freeform notes. Rejected: `context_routing` is a typed `{"docs": [...]}`
   payload; adding a freeform string variant would weaken the family's
   payload contract for no observed benefit.
3. **Move into a new singleton family.** A `project_notes` family with
   `{"text": "..."}` payload. Rejected: the data is empty and there are
   no consumers asking for it; adding a family for nothing is the
   anti-pattern the simplify doctrine's "Reuse" axis names directly.

Discard is the right default. If a future surface needs durable per-project
freeform text, that surface should arrive with a real consumer and a real
need; only then is it worth declaring a new family or column.

## Reversibility

The column drop is performed by the same `context_routing_cutover` module
that handles the typed cutover, with the same backup-on-write contract
governed by `record_audit_fingerprint`. If a future requirement surfaces,
the column can be restored from the timestamped backup file the cutover
writes alongside the live DB; subsequent application of any new
`project_notes` family would re-source from that backup once.

## Why the discard rides on the same cutover

`projects.notes` is dropped in the same `ALTER TABLE` sequence as
`context_always` and `context_by_topic` because all three retirements
ride on the same `pre_merge_breaking` exception pathway and share the
same single backup file and audit fingerprint. Splitting them across
modules would force two exception decision records, two backup files, and
two audit rows for one indivisible column-drop transaction.
