# Amend — change and reconcile

Recommend one fix task per actionable integration gap, or ask Add, Split, Reassign or Remove. Apply it with `workflow_item.epic_task.*` ([surfaces](surfaces.md)), sync GitHub issues and `worktree_plan`, then confirm no file sits in two worktrees and extend affected chain queues.

```text
yoke workflow-item epic-task simulation-get --epic "{epic-ref}" --phase integration
```
