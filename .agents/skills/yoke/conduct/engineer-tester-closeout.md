# Conduct — Tester closeout

Capture [reflections](dispatch-context-artifacts.md), stop this dispatch's
[preview env](dispatch-context-ephemeral.md) if one exists, then:

```text
yoke claims work release --epic PREFIX-N --task-num {task_num} --reason "tester return"
yoke workflow-item epic-task review-get --epic PREFIX-N --task-num {task_num}
```

No row but a text VERDICT: insert it; neither: [retry-budgets.md](retry-budgets.md).
PASS: [dispatch-context-dispatch.md](dispatch-context-dispatch.md); lagging
main never un-reviews a task. FAIL below --max-attempts:

```text
yoke conduct epic-task update-status --epic PREFIX-N --task-num {task_num} --status implementing --note "Retry attempt {attempt} of {max_attempts}"
yoke workflow-item epic-dispatch-chain update --epic PREFIX-N --worktree {BRANCH} --field current_attempt --value {attempt}
```

Then rerun the [loop](engineer-tester-loop.md). Exhausted: `--status failed`,
then [cleanup-report.md](cleanup-report.md) HALTED.

Renumbered migrations: rehearse the final modules
([databases.md](../../../../.yoke/docs/agents/rules/databases.md)), then record
the old-to-final map and audit ids before simulation:

```text
yoke items structured-field section-upsert PREFIX-N --field spec --section "Migration composition" --content-file SPEC_FACTS
```

Repeat with `--field worktree_plan`. Missing ledger access or rehearsal
receipt: halt before simulation.
