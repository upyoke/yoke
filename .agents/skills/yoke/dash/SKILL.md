---
name: dash
description: "File or execute spec-led Dash work through survey, isolation, verification, merge, and evidence."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "\"spec\" | {PREFIX-N}"
---

# /yoke dash

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

Execute the whole spec through delivery in this session; never split it for size. Start at [file-and-claim](file-and-claim.md); decisions: [escalate](escalate.md).

```text
yoke sessions touch --mode dash
```
