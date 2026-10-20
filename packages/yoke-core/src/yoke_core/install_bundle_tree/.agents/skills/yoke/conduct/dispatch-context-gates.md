# Conduct — task gates

First dispatch only: a `[CRITICAL]` plan gap halts unless --force/--ignore-gaps.

```text
yoke workflow-item epic-task simulation-get --epic PREFIX-N --phase plan --json
yoke workflow-item epic-task submission-receipt-get --epic PREFIX-N --task-num {task_num} --after-note-count {NOTE_COUNT}
```

Any receipt defect re-dispatches Engineer at the SAME attempt with:

> This is a bounded submission-only remediation (max 20 turns). Do NOT start new work.

A rescue commit stays a blocker. Gate passed:

```text
yoke workflow-item epic-task review-seed --epic PREFIX-N --task-num {task_num}
```
