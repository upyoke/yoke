---
name: models
description: Research and publish effective-dated model catalog revisions, then propose the level changes they imply.
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "lookup MODEL_ID | get | validate | diff | publish | revisions | restore | level-proposal"
---


# /yoke models

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

Reads need no item; a refresh without a claimed item files `/yoke dash` first.

1. `yoke update --check --json`: shipped levels arrive with the server release.
2. Research official provider pages; unknown values stay null.
3. Build the full catalog from the latest revision; validate, diff.
4. An org admin publishes on the diff's `base_revision_id`, effective now or later.
5. Propose levels: [level-proposals.md](level-proposals.md).

```text
yoke models publish --stdin --expected-base REV --source-note 'official sources checked YYYY-MM-DD' --json < candidate.json
```
