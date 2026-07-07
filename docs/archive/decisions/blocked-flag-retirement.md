# Item-level `blocked` is an orthogonal flag, not a lifecycle status

## Context

An earlier version of the backlog modelled "blocked" as one value of the
item lifecycle status enum. When the operator marked an item blocked, the
ticket lost its prior lifecycle position; clearing the block forced a
manual restore to whatever status the item held before. The pattern bled
into the scheduler, the frontier classifier, doctor health checks, label
sync, and the rendered board.

Two failures kept recurring:

1. Lifecycle position was destroyed by a block, so cancel/restore was
   lossy and operators had to guess the original status.
2. Doctor and resync flows had to distinguish "blocked because lifecycle
   said so" from "blocked because something external is wrong" — the same
   word carried two meanings.

## Decision

Item-level `blocked` is an **orthogonal flag** on the `items` row:

- `items.blocked INTEGER DEFAULT 0` — the flag.
- `items.blocked_reason TEXT` — operator-authored explanation.

Lifecycle status is preserved across `/yoke block` and `/yoke unblock`
— the flag toggles independently. The legacy `blocked` lifecycle status
is retained in the schema enum only so legacy rows surface as drift; new
writes never produce it.

GitHub labels follow the flag, not the status: the `status:blocked`
label was retired in favour of a flag-driven `blocked` label that mirrors
the same shape as `frozen`. The repair side recognises drift in either
direction.

The rendered body adds a `## Block` section when `blocked = 1`; doctor
ages the flag-driven blocks; the scheduler refuses to route blocked
items; the advance, merge, and done-transition preflight gates refuse
`blocked = 1`. Epic-task `blocked` is unrelated and kept its original
lifecycle semantics.

## Consequences

- `## Block` rendering, advance / merge / done-transition refusals, and
  blocked-label drift detection all share one signal: the flag.
- Doctor's blocked-flag health checks (post-cutover invariant, agreement
  between flag and reason, ageing of flag-driven blocks) replaced the
  status-driven checks.
- The legacy lifecycle value remains in `lifecycle_enums` and the schema
  CHECK constraint as drift bait; new writes never produce it.
- The blocked board row is part of the canonical 8-line stats box.
- `dispatch_status` returns `'blocked'` for flag rows even when the
  underlying status is something else (so dispatch lanes see a single
  truth).
