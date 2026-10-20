---
name: refine
description: "Read item artifacts, critique them, and write improved work item artifacts back through sanctioned Yoke update surfaces."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "{PREFIX-N}"
---

# /yoke refine {PREFIX-N}

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

No code edits. **Never subtract, only add:** keep every decision, AC,
question and evidence verbatim. **Escalate, don't correct:** a verified
wrong reference or scope conflict stops writes and advancement.

Read in order: [workflow-context.md](workflow-context.md),
[entry-and-gather.md](entry-and-gather.md), [survey-and-focus.md](survey-and-focus.md),
[review-rubric.md](review-rubric.md), [update-protocol.md](update-protocol.md).
Also [`readiness-repair.md`](readiness-repair.md), and
[blitz-execution-document.md](blitz-execution-document.md) if `ITEM_NEXT_SKILL=blitz`.
