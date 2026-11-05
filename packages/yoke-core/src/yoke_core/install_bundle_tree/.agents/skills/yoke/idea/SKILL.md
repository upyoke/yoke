---
name: idea
description: Create a new backlog item with a PREFIX-N ID. Infers project, workflow, priority, and flow from context.
argument-hint: "[--dry-run] [--workflow issue|epic|blitz|task] {title}"
---

# /yoke idea [--dry-run] [--workflow issue|epic|blitz|task] {title}

Operator decisions in this skill always use an Inbox decision request. Follow
`.yoke/docs/sessions/inbox.md#operator-questions`: workers route through steering
when a seat is live, otherwise use `decision-requests ask` directly; raise the
question in chat and record the answer with resolve. Use plain language, give the context needed to decide, name things in words (any id follows the name in parentheses), and keep the question very short.


Create one fully specified item. `--dry-run` comes first and writes nothing.

Ask for a missing title or outcome; keep the user's text verbatim. Then
Phase map: read [infer-and-create.md](infer-and-create.md),
[body-and-sync.md](body-and-sync.md) and [notes.md](notes.md).
