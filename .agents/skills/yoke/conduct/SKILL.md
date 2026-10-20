---
name: conduct
description: "Execute the pinned workflow segment bound to conduct through generated task lanes, the Engineer/Tester loop, and integration simulation."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "PREFIX-N [--max-attempts N] [--no-chain]"
---

# /yoke conduct PREFIX-N

Obey Workflow Execution Instructions and every AC.

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

```text
yoke sessions touch --mode conduct
```

## Phase map

Do NOT read all files upfront.

1. Entry: [entry-gates.md](entry-gates.md)
2. Claim and lanes: [entry-activation.md](entry-activation.md)
3. Tasks: [engineer-tester-loop.md](engineer-tester-loop.md)
4. Integration: [simulation-gate.md](simulation-gate.md)
5. Every exit: [cleanup-report.md](cleanup-report.md)

No parseable output: [retry-budgets.md](retry-budgets.md).

## Rules

- Continue after every subagent return; no pause or handoff menu.
- Orchestrate only: never edit code, tests or docs, run tests or simulate
  yourself, except [dispatch-context-verify.md](dispatch-context-verify.md).
- Before a retry or halt, read `yoke events tail --limit 20`.
- Never auto-waive blocking QA.
- Never merge, close issues, remove lanes or mark the item done. Hand off per
  [Stage-level routing](../../../../.yoke/docs/agents/levels.md).
