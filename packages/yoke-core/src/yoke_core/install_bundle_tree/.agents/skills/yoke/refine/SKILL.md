---
name: refine
description: "Read item artifacts, critique them, and write improved work item artifacts back through sanctioned Yoke update surfaces."
argument-hint: "{PREFIX-N}"
---

# /yoke refine {PREFIX-N}

Operator decisions in this skill always use an Inbox decision request. Follow
`.yoke/docs/sessions/inbox.md#operator-questions`: workers route through steering
when a seat is live, otherwise use `decision-requests ask` directly; raise the
question in chat and record the answer with resolve. Use plain language, give the context needed to decide, name things in words (any id follows the name in parentheses), and keep the question very short.


No code edits. **Never subtract, only add:** keep every decision, AC,
question and evidence verbatim. **Escalate, don't correct:** a verified
wrong reference or scope conflict stops writes and advancement.

Phase map: read in order: [workflow-context.md](workflow-context.md),
[entry-and-gather.md](entry-and-gather.md), [survey-and-focus.md](survey-and-focus.md),
[review-rubric.md](review-rubric.md), [update-protocol.md](update-protocol.md).
Also [`readiness-repair.md`](readiness-repair.md), and
[blitz-execution-document.md](blitz-execution-document.md) if `ITEM_NEXT_SKILL=blitz`.
A `level_change` handoff beats a release wait: `.yoke/docs/agents/levels.md`.
