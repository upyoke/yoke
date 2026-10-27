# The Frontier

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > The Frontier
<!-- /yoke:breadcrumbs -->

The Frontier is the ever-evolving set of actionable, filed work items that Yoke can move through their workflows. It connects your strategy to the work agents can pick up, advance, and deliver. The Frontier dashboard page is a view of that work, not the definition of the concept itself.

## From strategy to the Frontier

Strategy documents hold the rolling plan, including ideas not yet filed. Filing an item gives that work a workflow, requirements, and a durable identity. Non-terminal items remain part of the work Yoke must account for, including items waiting on dependencies or decisions.

Completed and cancelled work retain their history. They no longer compete for staffing as unfinished work. See [Strategy docs](strategy.md) and [Workflows and work items](work.md).

## Dependency graph and edges

### Blockers and dependents

A dependency edge connects a dependent item to a blocking item. It explains both when the dependent must wait and what the blocker must achieve. Edges can cross projects, so an application change can wait for an API change without losing that relationship between separate backlogs.

<!-- yoke:visual frontier -->

### Start, merge, and finish conditions

| Gate point | Meaning |
|---|---|
| Activation | Wait before starting implementation |
| Integration | Work may proceed, but merging must wait |
| Closure | Work may proceed, but completion must wait |
| Coordination only | Record an independent relationship without a lifecycle wait |

The satisfaction condition can require a workflow stage, a recorded merge, or completed delivery to a named environment. The rationale explains why the edge exists. Use the actual relationship rather than a generic blocked note when another item is the obstacle.

### Chains, unblocking value, and cycles

An item may unlock several downstream items. Longer chains reveal where a delay will propagate. A circular chain can leave every item waiting for another; Yoke refuses dependency edits that would create an unsatisfied cycle and reports existing deadlocks for resolution.

Your agent can inspect an item's edges and their reasons. [Dependency reference](../items/model/dependencies.md)

## Readiness and waiting

Readiness combines the item's pinned workflow, required gates, dependencies, approvals, blocks, freezes, and work ownership. An unfinished item is not necessarily assignable right now.

For example, an item may be ready to implement while an integration edge still prevents its merge. An item with finished code waiting only for that merge has no implementation step to staff. Read the reason and the gate point before assigning more work.

Claims protect existing ownership. A stopped or unresponsive worker needs recovery or a handoff, not a second agent silently taking the same assignment. [Gate reference](../workflows/gates.md)

## Scheduler and ranking

The scheduler ranks eligible work using priority, dependency relationships, current progress, and capacity. It aims to advance useful work while avoiding conflicting assignments and exceeding work-in-progress limits.

The next action comes from the item's pinned workflow. A scheduling result should therefore name both the work and the step it can take. A high-priority item with an unmet gate still needs its blocker resolved. [Scheduling reference](../strategy/charge-frontier.md)

## Advancing the Frontier

### Steering

A steering session maintains the working plan and coordinates execution across available sessions and machines. It files work, staffs it, follows delivery, and brings decisions to you. [Steering and fleet control](sessions.md)

### Charge

Use `/yoke charge` when you want an agent to pick up assignable work directly. It reads the ranked Frontier, presents the available work, and dispatches through the item's workflow. [Charge dispatch](../strategy/charge-dispatch.md)

### Feed

Use `/yoke feed` to refresh stale items and dependency facts or turn strategy work into filed items. Feeding changes the recorded work and its relationships; charging advances the work selected from that set.

## The Frontier dashboard page

The page shows **Waiting**, **On hold**, **Ready**, **Active**, **Release**, and recent **Done** work.

Waiting lays out unsatisfied dependencies in columns. The first column shows work holding other items up; later columns show how many dependency steps separate the work. Cards explain whether an item is waiting to start, merge, or finish. Coordination-only relationships do not appear as blocking edges.

On hold shows work held for its own reason, such as a freeze or block. Ready shows work available to advance. Active shows ongoing execution. Release and Done show delivery state, including the environment and relevant run.

Project filters retain related items across dependency chains, including items from other projects. Open a card to inspect blockers, dependents, and the item's full context. [Dashboard details](../strategy/frontier.md)
