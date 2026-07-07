# Path claims — render-relationship classifier reference

Quick reference for the render-target / render-source classifier
behaviour. Full path-claim reader contract lives across the existing
modules; this page captures the rendered-output behaviour so agents
grounding a claim-overlap question have a single landing page.

## Behaviour

Deterministic rendered files (`runtime/harness/{claude,codex}/agents/yoke-*.{md,toml}`)
are registered as `FAMILY_RENDER_TARGET` with their seed sources. When
two claims overlap solely on render-target paths AND their non-render
coverage is disjoint at the seed-source layer, the classifier consults
the renderer's seed-source registry and auto-returns
`OverlapClassification.NONE` — no operator-authored
`coordination_only` `item_dependencies` rows required.

## The two context families

- **`FAMILY_RENDER_TARGET`** (`render_target`) — attached to the
  path_targets row of a deterministic rendered file. Value:
  `{"sources": [<sorted seed-source path strings>]}`. One row per
  rendered file.
- **`FAMILY_RENDER_SOURCE`** (`render_source`) — attached to each
  seed-source path that contributes to one or more rendered outputs.
  `entry_key` is the rendered target path; value is
  `{"target": <rendered path>}`. Multiple rows per seed source (one
  per rendered consumer).

Constants live in
[`runtime/api/domain/path_context.py`](../../runtime/api/domain/path_context.py);
helpers and the renderer-bridge live in
[`runtime/api/domain/agents_render_path_context.py`](../../runtime/api/domain/agents_render_path_context.py).

## Classifier behaviour

`runtime/api/domain/path_claims_overlap.py` `classify_overlap`
applies one structural pre-check before the normal dep-graph
classification:

```
For each non-terminal claim that overlaps the candidate:
    If every shared target_id is in FAMILY_RENDER_TARGET
    AND the union of registered seed sources for those targets
        is disjoint from BOTH the candidate's and the other claim's
        non-render path coverage at the seed-source layer:
        SKIP this overlap (treat as NONE for this pair).
```

Three outcomes:

| Overlap shape | Verdict |
|---|---|
| Shared paths all render targets, disjoint seed coverage | auto-`NONE` |
| Shared paths all render targets, overlapping seed coverage | existing `INCOMPATIBLE` / `SERIAL_VIA_DEPENDENCY` |
| Shared paths mix render targets with hand-authored paths | existing semantics (falls through) |
| Shared paths all hand-authored | existing semantics (unchanged) |

## Registration

The renderer self-registers every Yoke agent packet's
target/source relationship via
[`record_render_relationships`](../../runtime/api/domain/agents_render_path_context.py).
Idempotent across re-runs (the unique key on `path_context_values`
overwrites in place). Triggered by `python3 -m
yoke_core.domain.agents_render render` and the `agents.render.run`
function-call surface.

Scope (v0): the 14 rendered packet outputs for the seven canonical
agents (7 Claude `.md` + 7 Codex `.toml`). Non-packet generated
surfaces (BOARD, event-catalog, function inventory, designs) are not
in scope for this slice.

## Integrity check

The `HC-path-integrity` doctor check now runs the
`render_relationship` invariant from
[`path_integrity_invariants_render_relationship`](../../runtime/api/domain/path_integrity_invariants_render_relationship.py).
Three failure shapes surface stale registrations:

- `stale_target` — `FAMILY_RENDER_TARGET` row references a deleted
  path_targets row (FK normally prevents; defense in depth).
- `missing_target_file` — rendered path not in the project's
  registry.
- `unregistered_source` — registered seed source path not in the
  project's registry.

## Skill-side resolution

Operator-facing workflow for path-claim overlap denial lives in
[`.agents/skills/yoke/idea/path-claim-blocking.md`](../../.agents/skills/yoke/idea/path-claim-blocking.md).
Section 0 names this auto-classification so operators understand why
some overlaps that would have required `coordination_only` edges now
resolve silently.
