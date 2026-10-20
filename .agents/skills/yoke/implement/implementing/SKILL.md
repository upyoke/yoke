---
name: implementing
description: "Implementation kickoff inside /yoke implement: QA seeding, project context, test commands, and implementation guidance. Called after the item enters its implementation stage."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: ""
---

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

# Implementing

Work only in WORKTREE_PATH. Widen claims before editing any uncovered file:

```text
yoke claims path list --item PREFIX-N --state planned --state active --state blocked
```

Read in order: [qa-seeding](qa-seeding.md), [project-context](project-context.md),
[test-and-record](test-and-record.md), [implementation](implementation.md).
