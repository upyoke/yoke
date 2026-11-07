---
name: implementing
description: "Implementation kickoff inside /yoke implement: QA seeding, project context and tests."
argument-hint: ""
---

# Implementing

Work only in WORKTREE_PATH. Widen claims before editing any uncovered file:

```text
yoke claims path list --item PREFIX-N --state planned --state active --state blocked
```

Read in order: [qa-seeding](qa-seeding.md), [project-context](project-context.md),
[test-and-record](test-and-record.md). Then implement against
`yoke items get PREFIX-N spec` and continue to [review](../review.md) without
ending your turn.

An undeclared schema, migration or bulk-data change stops coding until:

```text
yoke db-claim amend PREFIX-N --reason "implementation discovered governed DB mutation" --stdin
```
