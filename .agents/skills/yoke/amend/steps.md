# Amend — change and reconcile

No tasks: stop with `task_graph_missing`; never edit the body instead. Read the integration report (`--phase plan` only when none exists):

```text
yoke workflow-item epic-task simulation-get --epic "{epic-ref}" --phase integration
```

Recommend one fix task per actionable gap, or ask Add, Split, Reassign or Remove (remove only planning/planned tasks). Apply it with `workflow_item.epic_task.*` ([surfaces](surfaces.md)). Record each new task's GitHub issue with `metadata_update` `github_issue`; close a removed task's issue; refresh `worktree_plan`. Confirm no file sits in two worktrees, then extend each affected existing chain (Conduct creates missing ones):

```text
yoke workflow-item epic-dispatch-chain update --epic "{epic-ref}" --worktree "{worktree}" --field queue --value "{updated_queue_json}"
```
