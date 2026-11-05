---
name: dash
description: "File or execute spec-led Dash work through survey, isolation, verification, merge, and evidence."
argument-hint: "\"spec\" | {PREFIX-N}"
---

# /yoke dash

Operator decisions in this skill always use an Inbox decision request. Follow
`.yoke/docs/sessions/inbox.md#operator-questions`: workers route through steering
when a seat is live, otherwise use `decision-requests ask` directly; raise the
question in chat and record the answer with resolve. Use plain language, give the context needed to decide, name things in words (any id follows the name in parentheses), and keep the question very short.


Execute the whole spec through delivery in this session; never split it for size.

Phase map: [file-and-claim](file-and-claim.md), [survey-and-isolate](survey-and-isolate.md), [implement](implement.md), [verify](verify.md), [merge](merge.md), [close-out](close-out.md); decisions: [escalate](escalate.md).
