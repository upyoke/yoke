---
name: curate
description: Curate the Ouroboros learning log — cluster observations, promote field-notes to Dash, file work items for root causes.
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "(no arguments)"
---

# /yoke curate

Cluster unreviewed Ouroboros entries, file approved outputs, archive.

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

Start with [run.md](run.md).
