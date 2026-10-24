---
name: usher
description: "Unified merge+deploy command. Takes items from implemented through merge, deployment, and close-out. Inline orchestration skill -- no subagent spawned."
argument-hint: "PREFIX-N [PREFIX-N ...] [--dry-run] [--merge-only] [--deploy-only] [--resume PREFIX-N]"
---

# /yoke usher PREFIX-N [PREFIX-N ...]

Inline. Named items authorize execution. `--deploy-only` and `--resume` never
land again.

```text
yoke sessions touch --mode usher
```

Phase map: phases in order: [collect](collect.md), [plan](plan.md), [merge](merge.md),
[deploy](deploy.md), [finalize](finalize.md). A failure halts the batch. A `level_change` handoff beats a release wait:
[levels](../../../../.yoke/docs/agents/levels.md).
