# Conduct — amend cycle (once)

Write a fix task body: gaps, ACs, test plan, `## Files Touched`.

```text
yoke workflow-item epic-task add --epic PREFIX-N --title "Fix integration simulation gaps" --worktree {BRANCH} --context-estimate M --dependencies {DEPENDENCIES} --body-file {TASK_FILE}
yoke items github-sync PREFIX-N
yoke workflow-item epic-dispatch-chain update --epic PREFIX-N --worktree {BRANCH} --field queue --value '{UPDATED_QUEUE_JSON}'
yoke conduct epic-task update-status --epic PREFIX-N --task-num {FIX_TASK} --status implementing --note "Dispatched by conduct auto-fix" --claim-bypass "simulation-autofix:epic-PREFIX-N"
```

Then run one [loop](engineer-tester-loop.md)
with no retry. FAIL: AUTOFIX_HALTED. PASS: simulate again
([simulation-gate-criteria.md](simulation-gate-criteria.md)); CLEAN gives
AUTOFIX_CLEAN, else AUTOFIX_HALTED.
