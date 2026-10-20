---
name: simulate
description: Run the Simulator to trace cross-task integration paths and find gaps. Auto-detects plan phase or integration phase. --system for Ouroboros system-wide consistency audit.
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "{epic-ref} [--auto-fix] | --system"
---

# /yoke simulate {epic-ref} | --system

Pass the epic as PREFIX-N. No `yoke simulate` command exists; this skill
persists Simulator output.

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

```text
yoke sessions touch --mode simulate
```

Read [system](system.md) for `--system`; else [epic-flow](epic-flow.md),
[dispatch-prompts](dispatch-prompts.md), then [autofix-loop](autofix-loop.md).
