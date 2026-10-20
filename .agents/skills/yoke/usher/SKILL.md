---
name: usher
description: "Unified merge+deploy command. Takes items from implemented through merge, deployment, and done-transition. Inline orchestration skill -- no subagent spawned."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "PREFIX-N [PREFIX-N ...] [--dry-run] [--merge-only] [--deploy-only] [--resume PREFIX-N]"
---

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

# /yoke usher PREFIX-N [PREFIX-N ...]

Inline. Named items authorize execution. `--deploy-only` and `--resume` never
land again.

```text
yoke sessions touch --mode usher
```

Phases in order: [collect](collect.md), [plan](plan.md), [merge](merge.md),
[deploy](deploy.md), [finalize](finalize.md). A failure halts the batch. A `level_change` handoff beats a release wait:
[levels](../../../../.yoke/docs/agents/levels.md).
