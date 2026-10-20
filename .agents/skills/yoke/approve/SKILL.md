---
name: approve
description: "Record your decision on a deployment run paused at a Yoke human-approval stage."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "RUN-ID [--note \"...\"]"
---


<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

# /yoke approve RUN-ID [--note "..."]

```text
yoke deployment-runs approve RUN-ID --json
```

If `stage_approved` is false, report the outstanding approvers and stop; if true, resume the run from `current_stage`.
