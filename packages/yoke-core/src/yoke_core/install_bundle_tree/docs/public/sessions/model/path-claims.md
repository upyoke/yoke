# Path claims — render-relationship classifier reference

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Sessions](../index.md) > Path claim model
<!-- /yoke:breadcrumbs -->

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


Dash work holders use the same evidence packet during survey/isolation and
record an independent overlap with `yoke items dependency add ITEM HOLDER dash
--gate-point coordination_only --rationale "<shared paths and disjoint edits>"`.
Ordered edits wait for proven landing; uncertain independence goes through
`yoke say --steering`. Read dependency-add help for serving capability. Dash
claim selection can be restored to its pinned default with `yoke workflows
item-posture amend ITEM --key path_claims --clear --reason "<why>"`; live
coverage must first be released by its holder. Read amendment help for authority
and release recovery. [Lanes and claims](../../agents/rules/lanes-and-claims.md)
owns the full recipe.

## Ending coverage and reopening work

The holder may end an item-owned claim through `claims.path.release` or
`claims.path.cancel`:

```text
yoke claims path release --item PREFIX-N --claim-id N --reason "coverage finished"
yoke claims path cancel --item PREFIX-N --claim-id N --reason "coverage abandoned"
```

Acquire the owning item's work claim first. Release completes coverage; cancel
abandons it. These commands are idempotent for the same terminal state and
refuse another owner's claim. A released or cancelled claim cannot reopen.

Recording the merge landing releases every open item-owned path claim with
reason `landed`, on the landing's transaction, and unblocks downstream claims.
The work claim stays held through delivery. Landed items in a pinned stage
that implies merge need no open path coverage; released coverage remains
evidence for the merge boundary. Snapshot materialization writes all observed
planned targets together and emits one summary event, whose loss changes no fact.

Before reopening landed work, register fresh coverage for the complete touch
set, then prepare the lane to activate it:

```text
yoke claims path register --item PREFIX-N --paths path/to/file,path/to/other --allow-planned
```

The lifecycle rework gate and shared Bash/edit guards refuse missing fresh
coverage as `path_claim_rework_coverage_required`; the merge boundary still
checks the committed touched files. Use `--help` for release/cancel variants.

## Satisfied ordering

An ordering edge serializes overlapping claims only while its persisted
`satisfaction` is unmet. The classifier uses the same satisfaction evaluator
as lifecycle dependencies: recorded `fact:merged`, pinned status conditions
and attributed deployment facts all count. A satisfied edge permits overlap
without changing the stored `gate_point`; another unmet edge still serializes
the dependent. Unknown or unproven satisfaction never clears ordering.
