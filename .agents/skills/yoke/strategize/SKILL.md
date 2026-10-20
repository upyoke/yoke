---
name: strategize
description: "Direct-mode entrypoint — guided SML review across the MISSION, LANDSCAPE, VISION, MASTER-PLAN, and CURRENT-PLAN strategy docs."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "[--model MODEL]"
---

# /yoke strategize

Guided review and approved edits of the strategy docs.

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

Docs (MISSION, LANDSCAPE, VISION, MASTER-PLAN, CURRENT-PLAN) live in DB rows;
`.yoke/strategy/` is a gitignored render. Phases in order: [entry](entry.md),
[refresh](refresh.md), [research](research.md), [propose](propose.md),
[approve](approve.md), [finalize](finalize.md). Any abort releases the claim.
