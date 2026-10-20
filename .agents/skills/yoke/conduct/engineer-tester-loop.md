# Conduct — Engineer/Tester loop

Several tasks: [dispatch-context-dispatch.md](dispatch-context-dispatch.md).
Each task keeps its own lane, baselines and counters.

```text
yoke claims work acquire --epic PREFIX-N --task-num {task_num} --reason "engineer dispatch"
yoke workflow-item epic-task review-list --epic PREFIX-N --task-num {task_num}
```

Record TASK_BASELINE once, ATTEMPT_BASELINE per attempt. Add prior reviews
and notes as `## Prior Attempts` (over 3000 characters: latest 3 notes, 2
reviews), then dispatch Engineer
([dispatch-context-prompts.md](dispatch-context-prompts.md)). On return run
[dispatch-context-gates.md](dispatch-context-gates.md), merge the target
(conflicts go back to Engineer), then dispatch Tester:

```text
git -C {WORKTREE_PATH} merge {INTEGRATION_TARGET} --no-edit
yoke claims work acquire --epic PREFIX-N --task-num {task_num} --reason "tester dispatch"
```

Next: [engineer-tester-closeout.md](engineer-tester-closeout.md).
