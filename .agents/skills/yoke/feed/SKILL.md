---
name: feed
description: "Direct-mode entrypoint -- update stale frontier items, maintain frontier dependency facts, and materialize new work from the SML."
argument-hint: "[--no-new-items] [PREFIX-N ...] [--lane LANE] [--model MODEL]"
---

# /yoke feed

Direct-mode entrypoint for SML-to-idea materialization, stale-work-item refresh, and frontier dependency graph maintenance. Feed reads the Strategic Markdown Layer, the target frontier items, existing dependency edges, and recent codebase changes, then converges on one or more outcomes: leave work in the SML, refresh the graph only, update or sharpen current frontier items, or materialize new work items.

Feed is the canonical semantic owner of generated frontier-fact maintenance. It writes `source='feed'` dependency rows in `item_dependencies` with human-readable rationale and structured evidence, and it updates stale structured work item fields when recent landed work changed the frontier's ground truth. It does not own ranking, WIP caps, or claim handling (those belong to the scheduler and charge).

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `--no-new-items` -- Boolean flag. When set, feed runs the same analysis but is forbidden from creating new items, splitting work into new items, or advancing newly created work. If the analysis says new work items are needed, report "frontier insufficient, new work items suppressed by flag" instead of pretending sufficiency.
- `PREFIX-N ...` -- Optional explicit item scope. When present, feed still reads broader frontier/dependency context but deep-reads, stale-work-item updates, and reporting focus on the listed items.
- `--lane LANE` -- Execution lane identity (default: `DARIUS`).
- `--model MODEL` -- Model identifier override.

## Constants

```
REPO_ROOT=$(git rev-parse --show-toplevel)
_project=$(yoke projects checkout-context --field slug)
_project_id=$(yoke projects checkout-context --field id)
_prefix=$(yoke projects checkout-context --field public_item_prefix)
SML_SLUGS="MISSION LANDSCAPE VISION MASTER-PLAN CURRENT-PLAN"
```

## Philosophy

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent. Feed should turn strategy into backlog items that arrive with the current objective, standing constraints, and next action — enough to start, not a restated strategy dump.

**Maximalist intake.** Feed should materialize missing work, not merely sketch vague placeholders. Strategy gaps should become actionable items with clear rationale and blast radius.

**Truthful graph maintenance.** Feed's primary job is ensuring the dependency graph reflects reality, not just adding work items. A smaller, sharper, more truthful frontier is always preferred over a larger and noisier one. If two items share a hot file, unstable contract, schema surface, hook path, docs surface, test harness, or deployment surface, that relationship must be encoded as a real blocker row rather than left as prose.

**Recent landings redefine the frontier.** Feed must treat recently landed work as first-class input. If a merged change altered a file, contract, hook, schema, doc surface, or test harness that a frontier item assumes, feed updates that item's structured fields before pretending the frontier is still current.

## Phase map — read one file, at the phase it governs

| Phase | You are here when | Read before acting |
|---|---|---|
| 1–3. Parse, claim, dispatch | `/yoke feed` was just invoked | [`entry.md`](entry.md) |

The stage dispatch in `entry.md` names the one phase file each stage needs —
[`gather.md`](gather.md), [`decide.md`](decide.md),
[`materialize.md`](materialize.md), [`reconcile.md`](reconcile.md),
[`summarize.md`](summarize.md). Read the one the dispatch selects.

## Start

Read [`entry.md`](entry.md) and follow it.
