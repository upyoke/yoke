---
name: implementing
description: "Implementation kickoff inside /yoke implement: QA seeding, project context, test commands, and implementation guidance. Called after the item enters its implementation stage."
argument-hint: ""
---

# Implementing

Work only in WORKTREE_PATH. Widen claims before editing any uncovered file:

```text
yoke claims path list --item PREFIX-N --state planned --state active --state blocked
```

Read in order: [qa-seeding](qa-seeding.md), [project-context](project-context.md),
[test-and-record](test-and-record.md), [implementation](implementation.md).

For an operator decision, ask the live steering seat through `yoke say --steering`
with the question, context, options and recommendation. Without a live seat, file
`yoke decision-requests ask --key SLUG --question TEXT` directly. Do not wait on
a harness prompt tool; continue other in-scope work or end the turn. The answer
arrives as Fleet mail. Read `.yoke/docs/sessions/inbox.md#operator-questions`;
use `decision-requests list --mine` for history, `withdraw ID --reason TEXT` to
cancel your stale question, or `ask --replaces ID` to replace it without editing.
