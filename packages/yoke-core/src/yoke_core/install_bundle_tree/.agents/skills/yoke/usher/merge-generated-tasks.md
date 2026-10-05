# Usher — merge generated task lanes

Internal procedure selected by `generated_children=epic_tasks` and
`worktrees=worker_and_integration_lanes` in the item's pinned definition.
It is part of usher's merge phase, not a separate skill or entrypoint.
The parent work claim remains held through merge and delivery.

Read and execute these documents in order:

1. [Resolve the parent and task graph](merge-arguments.md).
2. [Check simulation, acceptance, terminal tasks, and merge order](merge-preflight.md).
3. [Merge every registered lane sequentially](merge-lanes.md).
4. [Record the landing and follow bound transitions](merge-bookkeeping.md).

Read [conflict recovery](merge-conflicts.md) when a lane merge refuses.
Halt the batch on any unresolved failure; preserve the parent claim and lane
state until the calling orchestration records its checkpoint and handoff.

For a read-only readiness report, the retained CLI remains available:

```bash
yoke merge audit {epic-id-if-provided}
```

The audit changes no database, Git, or GitHub state. It reports task
completion, lane heads and dirty state, simulation, dependency order,
status mismatches, and potential cross-lane conflicts. Run it before the
internal procedure when readiness is uncertain; an audit is not a landing.
