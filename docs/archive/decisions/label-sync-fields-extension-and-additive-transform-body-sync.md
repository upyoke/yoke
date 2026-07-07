# Sync gaps: LABEL_SYNC_FIELDS extension, section body sync, Step 8 observability symmetry, and compact-mirror-aware detection

**Status:** Decided 2026-05-19. Implements the four structural fixes that
collapse the 2026-05-19 detect-only baseline (2738 items checked, 2731
paired, 7 expected local-orphans, 2349 drifts) into the recoverable
post-backfill state.

## Why

A live `/yoke resync` detect-only run on 2026-05-19 returned 2349
drifts. The numbers came from three real Yoke → GitHub sync gaps plus
one detector defect:

| Drift field | Count | Underlying defect |
|---|---|---|
| `label-owner` | 1528 | `LABEL_SYNC_FIELDS` omitted `owner` |
| `label-source` | 434 | `LABEL_SYNC_FIELDS` omitted `source` (plus historical actor-label rename) |
| `body` | 381 (~341 real + ~40 false positive) | Section / additive transforms never told GitHub; detector had no compact-mirror awareness |
| `state` | 4 | `done_transition` Step 8 left DB ahead of GH when close failed silently |
| `label-status` | 2 | Same Step 8 failure cluster |

Three of the four root causes (label fields, section body sync, Step 8
observability) live inside the local-mutation path. The fourth is a
detector defect that produces a permanent false-positive loop. Each is
fixed independently below.

## Decision

### Defect 1 — extend LABEL_SYNC_FIELDS

`runtime/api/domain/backlog_queries.py:40` now reads:

```python
LABEL_SYNC_FIELDS = frozenset({
    "status", "priority", "type", "worktree", "source", "owner",
})
```

The downstream `actor_label_or_passthrough` resolver already renders the
current GH-surface label correctly for both columns, so no
actor-resolver changes are needed. The trigger at
`backlog_update_op.execute_update` consumes the frozenset unchanged.
`source` and `owner` writes currently route through the
`backlog_unsupported_field_writes` bridge; that bridge now owns both
actor-field writes and calls `_sync_labels` for every field present in
`LABEL_SYNC_FIELDS`.

### Defect 2 — section / additive transforms now sync body

The full-field replace path (`items.structured_field.replace`) has
always called `_sync_body` and emitted
`SyncFailed(operation="body", reason=...)` on transport failure. The
section paths did not. Every `items.section.upsert`,
`items.section.delete`, `items.progress_log.append`,
`items.structured_field.section_upsert`, and
`items.structured_field.section_append` mutated the DB-rendered body
without telling GitHub.

The fix is one shared helper —
`runtime.api.domain.sections.sync_body_after_section_mutation` — that
every section mutation path now calls after `_rerender_body` succeeds.
It pushes the freshly-rendered body to GitHub, emits
`SyncFailed(operation="body")` on transport failure, and returns
`(ok, reason)` so callers with a response envelope (function-call
handlers via `HandlerOutcome.warnings`; `TransformResult.warning` on
the item_field_transform sibling; CLI stderr message) can surface a
`github_sync_degraded` warning.

The DB mutation is durable regardless — `/yoke resync --fix` is the
canonical convergence mechanism, the same shape the full-field replace
path has had since the body-sync wiring originally landed.

A point worth recording: `items.structured_field.append_addendum` was
NOT in the gap. It already routes through `execute_structured_write`,
which calls `_sync_body` and emits `SyncFailed(operation="body")`. The
gap was only on the section / append-via-section paths.

### Defect 3 — `done_transition` Step 8 observability symmetry

The bundled `sync_done_item` call in `done_transition` Step 8 covered
labels + body + close in one GraphQL operation. On non-zero rc the path
recorded `step_marker="8-degraded"` and a `github_sync_degraded`
warning, but no structured `SyncFailed` event was emitted — the body
path emits it on transport failure, the close path did not. Result: 4
items (YOK-1591, YOK-1594, YOK-1665, YOK-1704) closed locally while
their GitHub issues remained OPEN, with 2 carrying stale
`status:release` labels.

Two changes restore observability symmetry:

1. **`backlog_rendering._close_issue` is now the single owner of
   `SyncFailed(operation="state")` emission.** Both failure branches —
   non-zero rc from `backlog_github_sync.close_issue` and the broad
   `except Exception` — call `_record_sync_failure(item_id, "state",
   reason)` before returning False. Every caller
   (`backlog_update_op.execute_update`, `backlog_close_op.execute_close`,
   plus the wrappers above) inherits the emission for free.

2. **`done_transition_github_sync.apply_step_8`** now also emits
   `SyncFailed(operation="state")` when the bundled `sync_done_item`
   returns degraded. The reason names the step
   (`done_transition step 8 degraded: …`) so resync analysis can
   distinguish per-operation close failures from the bundled path.

This is **not** a transaction-shape redesign. The local mutation still
commits ahead of GitHub when the bundled call partially fails; the new
event surface is what gives `/yoke resync --fix` something to
converge against. The duplicate emit that previously lived in
`backlog_update_op.execute_update` was removed — `_close_issue` is now
the single owner, so callers do not need to duplicate the emission.

### Defect 4 — compact-mirror-aware detector

The write side has always published a compact mirror with the
deterministic footer
`_Body exceeded GitHub's size budget; full content stays in the DB._`
when the rendered body exceeds the 62 000-byte GitHub budget. The detect
side at `stage2_compare` had no compact-mirror awareness — it
byte-compared `normalize_body_for_compare(local)` against
`normalize_body_for_compare(gh)`. Forty live items render bodies over
budget; each was flagged as `body` drift on every detect run, `--fix`
re-pushed the same compact mirror, and the next detect run flagged the
same item — a permanent false-positive loop.

The fix teaches the detector the compact-mirror contract via
`runtime.api.engines.resync_detect_compact_mirror.matches_compact_mirror`,
which `stage2_compare` calls from the body-comparison block:

1. If the GH body does **not** contain `COMPACT_MIRROR_FOOTER`, no
   suppression — fall through to the existing byte-compare.
2. If the local body is **not** over budget, no suppression — the
   legitimate "shrink back to full" path emits real drift that `--fix`
   resolves.
3. Otherwise, recompute the expected compact mirror via
   `render_compact_mirror(local_fields, conn=None, item_id=…)`, strip
   the volatile `## Evidence` section content from both sides (the
   single Evidence summary line legitimately changes between syncs),
   and only suppress drift when the stripped forms match.

Stale mirrors (wrong title, wrong status, wrong type) still produce
real drift because they fail the recomputed-mirror match.

## Alternatives considered and rejected

- **Rollback the local DB on GH close failure.** Out of scope. The
  transaction-shape redesign required for true rollback is much larger
  than this slice; observability-symmetric `SyncFailed` plus
  `--fix`-based convergence is the minimum honest fix.
- **Rework `sync_done_item` into three independent retryable calls.**
  Out of scope. Same rationale — observability is enough.
- **Backfill historical `SyncFailed` events for closed-out items.** Not
  worthwhile; the live `--fix` run after the structural fixes land
  resolves the actual drift either way.
- **Touch `_render_actor_token` or `actor_label_or_passthrough`
  semantics.** Defect 1's fix is two strings in a frozenset; the
  resolver already returns the correct current GH-surface label.
- **Add an `items.section.append` function id.** AC-8: not needed. The
  registered surfaces `items.progress_log.append` and
  `items.structured_field.section_append` already cover the append
  needs.

## Backfill convergence

After all four fixes land:

1. Run `/yoke resync --fix` once on the full backlog. This pushes the
   missing `source:` / `owner:` labels (1962 items), refreshes the
   diverged bodies (~341 items), and converges the 4 state + 2
   label-status laggards.
2. A follow-up `/yoke resync` detect-only run reports zero drift in
   the `label-owner`, `label-source`, `state`, and `label-status`
   categories. The ~40 compact-mirror false positives are now
   suppressed. The remaining `body` drift count is ≤ 10 (slack for
   items whose section-write happens between fix and verification).
3. The 7 local-orphan `epic_task` children of YOK-1687 stay as-is — by
   design, `epic_task` children do not carry their own GH issues.
