---
name: blitz
description: "Execute a substantial document-led Blitz as integrated slices with continuous plan evidence."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "{PREFIX-N}"
---

# /yoke blitz {PREFIX-N}

Execute one Blitz from its linked strategy document; create no child items.

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

```text
yoke sessions touch --mode blitz
```

Phases: [read-and-survey](read-and-survey.md), [integrate](integrate.md),
[review-and-complete](review-and-complete.md). A `level_change` handoff beats
a release wait: `.yoke/docs/agents/levels.md`.
