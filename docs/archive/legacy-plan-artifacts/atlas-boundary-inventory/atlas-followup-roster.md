# Atlas follow-up roster

Generated from the first Atlas integrity audit (2026-05-27) under `projects/yoke/qa-artifacts/1685/atlas-integrity-2026-05-27/report.json`. This roster is the operator-authored interpretation of the audit's `followup_candidates` block — it groups outstanding work into the four buckets the YOK-1685 spec calls for and points at the next 1–2 Stage 2 conversion slices.

## Cloud blockers

Work that must land before a project repo without a Yoke checkout can use cloud Yoke safely. These items widen the agent surface area or close API boundaries that today still require an in-checkout `python3 -m runtime.*` fallback.

1. **Stage 2 conversion slice: `db_router items` family.** The largest pending bucket on the operation tracker is the remaining `db_router` item-read fallbacks (`items list`, `items search`; `items get` is already wrapped). Wrapping these under `yoke items ...` adapters retires the most agent-facing `python3 -m yoke_core.cli.db_router` recipes and is the cleanest next slice — it removes the largest single block of "operator-debug fallback" prose from the agent-facing teaching surface.
2. **Stage 2 conversion slice: `db_router events` family.** Second-largest bucket; converting `events list/tail/count/anomalies` to `yoke events ...` closes the events query surface that agents reach into during refine / advance / polish.
3. **`db_router qa requirement-add` and friends.** QA seeding is one of the highest-volume agent surfaces during `/yoke refine` and `/yoke conduct`; consolidating it under `yoke qa requirement ...` removes a class of agent confusion.

The audit's `operation_tracker.by_status.pending=32` rows are the exhaustive list; the first slice should pick whichever family has the smallest payload-schema risk to test the conversion grammar end-to-end before fanning out.

## Teaching drift

Skill / packet / help / denial mismatches that confuse agents but do not block cloud infrastructure.

1. **`claims work holder-get` flag vs positional.** YOK-1847 promised a `--item YOK-N` shape but the live adapter accepts a positional `<YOK-N>`. Audit records this as one of the seed contradictions; resolving it means either landing the `--item` flag on the adapter (preferred — matches the wider grammar) or correcting the promise in retrospect.
2. **`yoke ouroboros field-note list/get` adapter.** No agent-facing read surface for field-notes exists today; the audit reads `ouroboros_entries` directly. A small new adapter (likely `yoke ouroboros field-note list --limit N --since DATE`) lets agents inspect their own recent notes without operator-debug raw SQL.
3. **Field-note footer drift on lints.** The audit reports `0 / 60` lint modules statically reference the field-note footer text. Most lint denial messages do already include the footer — the audit's detection heuristic is conservative. A small slice could either tighten the detector or audit which lint denials actually emit the footer at runtime, and gap-fill the ones that don't.

## Cleanup

1. **Periodic stale-reference sweep.** After future Stage 2 conversion slices land, run a fresh Atlas audit and check for new stale references — any doc / agent body / packet / lint that points at a now-replaced surface. YOK-1685 owns the first pass; future slices should look for stragglers and resolve them.

## Future catalog work

Full seven-axis Atlas catalog / Stage 3 family coherence — explicitly out of scope for YOK-1685 per the ticket's `## Out Of Scope` block.

1. **Seven-axis `atlas_policy.py` catalog.** The full code / architecture / paths / docs axes remain future Stage 3 work. The audit JSON is the absorption seam: when the seven-axis renderer lands, it consumes the audit JSON rather than re-collecting.
2. **Deep Python call-graph analysis.** Inventorying every Python function an agent could theoretically import is intentionally not in scope. The harness inventories live registered functions, CLI surfaces, tracker rows, teaching places, lints, and field-note evidence. Call-graph analysis remains future catalog work unless a future report proves it is a cloud blocker.
3. **Atlas dashboard / time-series.** The audit produces one JSON snapshot per run. Future tooling could trend pending / wrapped / contradiction counts over time so cutover progress is visible.

## Next 1–2 Stage 2 slices (recommendation)

Based on `operation_tracker.by_status.pending=32` and the audit's static evidence:

1. **`db_router items` -> `yoke items ...` Stage 2 slice.** Highest agent-volume surface; smallest schema surface area for the conversion grammar.
2. **`db_router events` -> `yoke events ...` Stage 2 slice.** Second-highest agent-volume surface; already half-wrapped (`events.query.run` exists as a function id); the slice mainly extends the adapter set.
