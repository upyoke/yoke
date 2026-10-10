# Path claims — render-relationship classifier reference

Quick reference for the render-target / render-source classifier
behaviour. Full path-claim reader contract lives across the existing
modules; this page captures the rendered-output behaviour so agents
grounding a claim-overlap question have a single landing page.

## Behaviour

Deterministic generated outputs in the source inventory
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
`yoke_core.domain.path_context`;
helpers and the renderer-bridge live in
`yoke_core.domain.agents_render_path_context`.

## Classifier behaviour

`yoke_core.domain.path_claims_overlap.classify_overlap`
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

The renderer registers each known generated output's
target/source relationship via
`yoke_core.domain.agents_render_path_context.record_render_relationships`.
Idempotent across re-runs (the unique key on `path_context_values`
overwrites in place). Use `yoke agents render`; read its `--help` for target
root and dry-run options. The client resolves an explicit project, `YOKE_PROJECT`,
or its registered checkout and sends that project with the relationship refresh.
The server refuses a missing project as `project_required` before writing; it
never attributes relationships using its own checkout. An unattributed client
skips this advisory registration while still rendering the requested files.

`yoke_core.domain.render_relationship_inventory` owns the complete map:
agent adapters for each declared harness, Atlas, event catalog and tracked
install-bundle mirrors. Tracked inputs determine their seed sets. A generator
preserving authored content self-seeds that output, including the event
catalog appendix, so it cannot receive the output-only escape. An install
target without a tracked source also self-seeds. Do not infer independence
from a generated-looking filename or a fixed adapter count.

## Integrity check

The `HC-path-integrity` doctor check now runs the
`render_relationship` invariant from
`yoke_core.domain.path_integrity_invariants_render_relationship`.
These failure shapes surface stale registrations:

- `stale_target` — `FAMILY_RENDER_TARGET` row references a deleted
  path_targets row (FK normally prevents; defense in depth).
- `missing_target_file` — rendered path not in the project's
  registry.
- `unregistered_source` — registered seed source path not in the
  project's registry.

## Skill-side resolution

Operator-facing workflow for path-claim overlap denial lives in the Yoke
source-tree skill doc `.agents/skills/yoke/idea/path-claim-blocking.md`.
Section 0 names this auto-classification so operators understand why
some overlaps that would have required `coordination_only` edges now
resolve silently.
