---
name: resync
description: Detect and repair drift between local backlog items and their GitHub issues. Default mode is detect-only (read-only); use --fix for auto-repair.
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "[--fix]"
---


<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

# /yoke resync [--fix]

```text
yoke resync --fix
```

Omit `--fix` to only detect. Show each mismatch and each repair actually made;
never claim an unperformed repair.
