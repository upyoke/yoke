# Conduct — sync, enumeration and lanes

```text
yoke workflow-item epic-dispatch-chain list --epic PREFIX-N --json
yoke items github-sync PREFIX-N
yoke lifecycle transition PREFIX-N --from {LIVE_STAGE} --to {IMPLEMENTING_STAGE} --reason "Conduct: synced graph ready for activation" --json
```

No chains: github-sync builds them. Stages come from the pin.

In-flight chain head_dispatch.decision: resumable → candidate; busy → skip;
blocked → report, no writes; unknown → halt it. Other chains:

```text
yoke workflow-item epic-dispatch-chain advance --epic PREFIX-N --worktree {BRANCH}
```

Path-claim overlaps: [lanes-and-claims.md](../../../../.yoke/docs/agents/rules/lanes-and-claims.md).

```text
yoke worktree prepare --item PREFIX-N --project {PROJECT}
git -C {WORKTREE_PATH} merge {PREDECESSOR_BRANCH} --no-edit
yoke conduct epic-task update-status --epic PREFIX-N --task-num {task_num} --status implementing --note "Dispatched by conduct (task fan-out)"
yoke workflow-item epic-dispatch-chain refresh-activation --epic PREFIX-N --worktree {BRANCH} --task-num {task_num}
```

A task branch with no lane: `yoke item-worktrees create`, then
`yoke workflow-item epic-task reassign`, then `yoke item-worktrees path-record`.
Merge each Cross-Task Merge Plan predecessor; one not reviewed or done, or a
conflict, halts for authoring repair; one not in the task's dependencies halts
`task_dependency_missing`. Dispatch Engineer only when the task reads
implementing or reviewing-implementation.
