---
name: feed
description: "Direct-mode entrypoint -- update stale frontier items, maintain frontier dependency facts, and materialize new work from the SML."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "[--no-new-items] [PREFIX-N ...] [--model MODEL]"
---

# /yoke feed

SML materialization, stale-work-item refresh and generated frontier-fact
maintenance. Feed owns `source='feed'` dependency rationale/evidence and stale
structured-field updates; scheduler/charge own ranking, WIP caps and staffing.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments and context

- `--no-new-items`: analyze normally; suppress creates, splits and advancing
  newly created work. Report “frontier insufficient, new work items suppressed
  by flag” when those actions are needed.
- `[PREFIX-N ...]`: ordered explicit targets; deep reads, mutations and reporting
  focus there while retaining enough surrounding graph context.
- `--model MODEL`: override, otherwise session default.

Resolve checkout root with `git rev-parse --show-toplevel`; project slug/id/prefix
with `yoke projects checkout-context --field <field>` for `slug`, `id`,
and `public_item_prefix`.
SML: MISSION, LANDSCAPE, VISION, MASTER-PLAN, CURRENT-PLAN.

Materialize actionable missing work with objective, standing constraints, next
action and blast radius. Prefer fewer sharper items and a truthful graph.
Recent landings redefine assumptions; encode real shared-file/contract/schema/
hook/docs/test/deployment sequencing in dependency rows.

## Phase map

Follow [entry.md](entry.md). Subsequent phases are
[gather.md](gather.md), [decide.md](decide.md), [materialize.md](materialize.md),
[reconcile.md](reconcile.md), [summarize.md](summarize.md); read each when reached.
