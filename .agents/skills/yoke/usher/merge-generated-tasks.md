# Usher — merge generated-task lanes

This is merge's internal procedure for effective epic_tasks and
worker_and_integration_lanes, not a separate command/skill. Parent claim stays
held through merge/delivery. Execute in order:

1. [Resolve supplied ref, exact policies and registered graph](merge-arguments.md).
2. [Simulation, all criteria, completion posture and order](merge-preflight.md).
3. [Sequential registered lane landing and regression check](merge-lanes.md).
4. [Verified parent receipt and pinned transitions](merge-bookkeeping.md).

Read [conflict recovery](merge-conflicts.md) on refusal. Halt on unresolved
failure, preserving parent claim and lane state until checkpoint/handoff.
Optional readiness audit is read-only and not landing:

```text
yoke merge audit PREFIX-N
```

It reports task completion, heads/dirty state, simulation, dependency order,
status mismatches and cross-lane conflicts; uncertainty can warrant it.
