# B8 board-activity semantics: full-history backfill, reduced go-forward

## Decision

The board's lifetime-activity, streak, and velocity metrics read the
`item_activity_days` state table. Its rows come from two regimes:

1. **History (one-time backfill, full legacy semantics).** The governed
   migration `runtime/api/domain/migrations/item_activity_state.py`
   seeded the table from one scan of the events ledger using the frozen
   legacy activity-event-type set (the 19-type
   `LEGACY_ACTIVITY_EVENT_TYPES` constant in the migration module,
   including the agent-attribution types `tool_call` and
   `session_lifecycle`). Historical streaks and lifetime percentages
   survive the cutover unchanged — to the extent the ledger still held
   them: INFO-severity retention (30d) had already decayed parts of the
   live semantics, so the backfill is the best remaining record either
   way.

2. **Go-forward (reduced semantics).** New rows are written only by REAL
   item-scoped domain mutations, each at its own mutation site:
   - status transitions (item + epic task) via
     `runtime.api.domain.item_status_transitions`,
   - work-claim acquire and deliberate release (item / epic-task
     targets),
   - structured-field, section, and Progress-Log writes,
   - epic-task body/metadata mutations and progress notes,
   - qa requirement/run writes.

   "Touched" no longer includes raw tool-call or session-lifecycle
   attribution: an agent reading files against an item, or a session
   merely starting with an item claim held, does not mark the item
   active. System janitorial paths (stale-session reclaim sweeps,
   reactivation reacquire) are deliberately NOT activity — a dead
   session being cleaned up is not work on the item.

## Why no emit_event chokepoint

A single rollup hook inside `emit_event` (or any per-event-type trigger
table) would make board STATE depend on the telemetry pipeline — the
exact state-on-telemetry inversion B8 removes. Telemetry severity
gates, capture modes, isolation gates, and retention policy must never
decide whether an item counts as touched. So the rollup is maintained
by direct `touch_item_activity` calls at the domain mutation sites
themselves; the events ledger stays telemetry-only.

## Disposition of `activity_events.py`

Deleted (with its tests). The 19-type set survives only as the frozen
`LEGACY_ACTIVITY_EVENT_TYPES` constant inside the backfill migration —
the single remaining consumer of the historical semantics. The
"repurpose as rollup trigger set" option was rejected because the
go-forward semantics are mutation-site-owned, not event-type-owned.

## Invalidation watermark

The legacy cross-process board cache invalidated on the `events.id`
high-water mark. The equivalent: `item_activity_days.id` (surrogate
monotonic key; the natural key `(project_id, item_id, day)` is enforced
UNIQUE). New tuples always land with a higher id; same-day re-touches
conflict away without changing counts; `MAX(id)` equality therefore
proves cache freshness. `runtime/api/board/activity_cache.py` owns the
read; cache version bumped to 2 at the cutover.
