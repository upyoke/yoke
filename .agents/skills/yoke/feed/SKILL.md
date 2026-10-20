---
name: feed
description: "Direct-mode entrypoint -- update stale frontier items, maintain frontier dependency facts, and materialize new work from the SML."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "[--no-new-items] [PREFIX-N ...] [--model MODEL]"
---

# /yoke feed

Refresh stale items and Feed's dependency rows; file strategy work.

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

`--no-new-items` creates nothing; `PREFIX-N` args set the focus. Start with
[entry.md](entry.md).
