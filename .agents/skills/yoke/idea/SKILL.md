---
name: idea
description: Create a new backlog item with a PREFIX-N ID. Infers project, workflow, priority, and flow from context.
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "[--dry-run] [--workflow issue|epic|blitz|task] {title}"
---

# /yoke idea [--dry-run] [--workflow issue|epic|blitz|task] {title}

Create one fully specified item. `--dry-run` comes first and writes nothing.

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

```text
yoke sessions touch --mode idea
```

Ask for a missing title or outcome; keep the user's text verbatim. Then
read [infer-and-create.md](infer-and-create.md),
[body-and-sync.md](body-and-sync.md) and [notes.md](notes.md).
