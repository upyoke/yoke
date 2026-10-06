# /yoke advance — arguments and skip flags

Read this when an invocation carries a flag. The phase steps do not need it.

## Arguments

- `{PREFIX-N}` — Backlog item ID. Accepts prefixed IDs, zero-padded prefixed IDs, or bare numeric IDs.
- `[status]` — Optional target status. If omitted, advances to the next status in the lifecycle. Implementation entry is not an advance target: the stage skill bound across it is `/yoke implement`, which owns the engine entry, the implementation sub-skill, and the review loop.
- `--env <name>` — Optional. Update the item's `deployed_to` field. Valid environments are resolved per-project from DB tables (`environments` via `sites`, `project_capabilities`). Can be combined with a status advance or used standalone on an already-done item.
- `--force` — Optional. Override the file-level collision blocker, generated-task existence/completion gates, or merge verification gate.
- `--skip-polish` — Optional. Operator-asserted fast path across the pinned `polish` skill segment. Dispatches through the advance skill's internal skip handler (`yoke_core.domain.advance_skip`; no registered product CLI wrapper), derives the hops from the binding's `from_stage_id`, `through_stage_id`, ordered stages, and transitions, emits a `SkipHopPerformed` event, and releases the item claim with reason `handoff-to-usher`. Requires the current status to equal that pinned binding's entry stage. Use when the current mission explicitly declares that polish is unnecessary, such as a bounded theme swap whose acceptance criteria require no implementation review. Do NOT infer a skip from the item title, and do NOT pass a target status with this flag — the flag owns the target.
- `--skip-refine` — Optional. Operator-asserted fast path across a pinned `refine` skill segment's gate-free bookkeeping rungs. The internal skip handler (`yoke_core.domain.advance_skip`; no registered product CLI wrapper) validates the current stage against its allowlist and advances to that binding's handoff. It emits a `SkipHopPerformed` event. Use when refine deliberation is unnecessary (low-risk content swaps, copy edits). Do NOT pass a target status with this flag.

Both skip flags:
- Are operator-discoverable via `/yoke advance --help` when the mission declares a skip.
- Emit an `ItemStatusChanged` event with `source=skip-polish` or `source=skip-refine` (honest telemetry for Ouroboros).
- Use distinct `YOKE_CLAIM_BYPASS` reasons (`skip-polish`, `skip-refine`) so the pre-implementation safety invariant (claim-bypass only for gate-free bookkeeping rungs) stays intact.
- Refuse invalid current statuses with a clear error. The bypass is operator-asserted, not auto-inferred.

Example invocations:

```bash
# Theme-swap mission declares "SKIP: polish":
/yoke advance PREFIX-N --skip-polish

# Low-risk copy edit declares "SKIP: refine":
/yoke advance PREFIX-N --skip-refine
```
