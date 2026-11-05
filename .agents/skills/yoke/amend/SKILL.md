---
name: amend
description: Add, split, reassign, or remove tasks after sync. Re-verifies overlap and updates GitHub.
argument-hint: "{epic-ref}"
---

# /yoke amend {epic-ref}

Operator decisions in this skill always use an Inbox decision request. Follow
`.yoke/docs/sessions/inbox.md#operator-questions`: workers route through steering
when a seat is live, otherwise use `decision-requests ask` directly; raise the
question in chat and record the answer with resolve. Use plain language, give the context needed to decide, name things in words (any id follows the name in parentheses), and keep the question very short.


Internal to Conduct. Hold the epic claim; never amend during its dispatch.

Phase map: [steps](steps.md).
