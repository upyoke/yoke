# Durable validation reports

Read before writing or recording a report.

## Persist the verdict

For an epic task, use the exact epic ref and task number from the dispatch;
never derive them from a title. Record the full HEAD of the clean task lane
before reviewing; a PASS must name it:

```bash
yoke workflow-item epic-task review-insert --epic {epic-ref} \
  --task-num {task-num} --verdict {pass|fail} --head-sha {reviewed-head-sha} \
  --body-file /tmp/yoke-review.{task-num}.md
```

Use `--stdin` instead of `--body-file` when you cannot write a scratch file. A
passing review advances the task. Without an epic task, return the report in
your final message.

The verdict is binary: no conditional pass. A blocker fails it; an
informational warning does not.

## Report template

In order: `# Validation Report: {item or task}`, `## Result: PASS | FAIL`,
`## Acceptance Criteria` (PASS or FAIL for each), `## Tests` (selected and
excluded, with reasons), `## Test Commands Used`, `## E2E Validation`,
`## Regression Analysis`, `## Interface Contracts`, `## Documentation`,
`## Code Quality`, `## Path Tracing`, `## Issues Found` (exact failure and
`file:line`), `## Recommendation`.
