# Steering report dependency sections

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Functions](index.md) > Steering dependencies
<!-- /yoke:breadcrumbs -->

Two sections of the [steering fleet report](../sessions/steering-report.md) read the
live waiting graph: every unsatisfied blocking edge (`activation`,
`integration`, `closure`) whose dependent is not terminal, as the shared
dependency kernel evaluates it. `coordination_only` edges never block, so they
never appear. Both sections print in the short and full report
(`yoke steering report get`) and in the digest the hook and fleet watcher
deliver. One evaluation of the graph feeds both.

## Dependency deadlocks

Each loop of blocking edges among live items that the backend detector finds
(`dependency_cycles`) prints once: loop order, every edge with its id and gate,
the work it strands, and the recovery — make one edge `coordination_only`, or
route the ordering decision to steering. A loop never clears on its own, so any
row is actionable.

## Waiting chains

The same edges the Frontier's dependency model draws
(`ui/static/frontier_dependency_model.js`: "holding work up", "unblocks N",
"N steps behind") print as compact rows, loops excluded:

- A **head** is a blocker that waits on nothing live itself. It prints when it
  holds more than one item, directly or down the chain.
- An **unstarted link** prints with `!`. It is a blocker still before its
  workflow's implementation segment, with no live work claim, while an item
  behind it is in progress (past implementation entry or claimed). It prints
  whether it is a head or sits mid-chain, because either way nothing behind it
  moves until someone starts it.

Each row names the blocker, its stage and staffing, how many items it unblocks,
the chain depth below it, each edge it holds directly (`DEPENDENT (gate
satisfaction #id)`), and what it waits on. Rows sort flagged first, then by
items unblocked and depth. A chain that crosses projects is one chain: a row
stays when any item in it belongs to the scope, and a seat narrowed to a
strategy document sees rows touching its items. The JSON report carries the
rows as `waiting_chains`; the age-blind fingerprint changes when a blocker
starts or stops printing, or gains or loses its flag.

Example:

```text
waiting chains — blockers holding the most work; ! marks an unstarted, unstaffed blocker with work behind it in progress:
  ! PREFIX-12 (idea, unstaffed) unstarted while PREFIX-14 in progress; unblocks 3, 2 deep; holds PREFIX-14 (activation status:done #820); waits on PREFIX-10
  PREFIX-10 (implementing, staffed) unblocks 4, 3 deep; holds PREFIX-12 (activation status:done #815)
```

## Waiting to land

An `integration` edge holds back a merge, not a start, so an item behind one
is normally free to build and reads as ready. Once its active implementation
lane has a recorded commit (`item_worktrees.commit_sha`), building is done and
landing is all that is left. If its only unmet edges are `integration` edges,
the Frontier computation holds it as waiting, with one sentence naming each
blocker and what it still has to do:

```text
waiting to land — committed, unclaimed, held only until each named blocker lands; not available:
  PREFIX-20  Waiting on PREFIX-14, PREFIX-15 to merge  Ship the report section
```

The same rule and sentence reach every surface that says what is ready: the
report lists unclaimed such items here instead of under available work
(`landing_waits` in the JSON), and `frontier.list` (`yoke frontier list` and
the web Frontier) marks their blocked rows `holds_pickup` with that sentence,
so the item sits in Waiting rather than Ready. Any unmet `activation` edge
keeps its own wait reason instead. When the blockers land the item is ready
again for whoever lands it.

## Keep dependencies minimal

Every edge holds real work back, so steering adds the lightest edge the work
needs and removes the rest:

- Before adding an edge, confirm the dependent truly needs the blocker's merged
  code. Shared files alone call for `coordination_only`.
- Prefer the narrowest gate and condition: `coordination_only` over
  `integration` over `activation`, `fact:merged` over `status:done`, and a
  specific task over a whole epic.
- On every report read, check the waiting-chains rows. Staff a `!` blocker or
  remove its edge with `yoke items dependency remove`. Narrow an edge heavier
  than needed with `yoke items dependency update DEPENDENT BLOCKING
  --match-gate-point GATE --gate-point coordination_only` or
  `--satisfaction fact:merged`, giving the reason in `--rationale`.
