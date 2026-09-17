# /yoke amend — function-call surfaces

## Function-call surfaces

All task mutations route through the `workflow_item.epic_task.*`
function family. See
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)
for the universal envelope shape and the per-function payload
contracts. The functions amend uses:

- `workflow_item.epic_task.add` — create a new task on the epic.
- `workflow_item.epic_task.body_replace` — write or replace a task's
  body content (the function-call replacement for the prior
  `epic task-update-body` choreography).
- `workflow_item.epic_task.split` — split one task into N children
  with rewritten dependencies.
- `workflow_item.epic_task.reassign` — move a task to a different
  worktree.
- `workflow_item.epic_task.remove` — close + retire a task that is at
  `planning` or `planned`.
- `workflow_item.epic_task.metadata_update` — update one or more
  scalar fields (`github_issue`, `dependencies`, etc.) atomically.

Worktree-plan edits route through
`items.structured_field.replace` (`field: "worktree_plan"`) on the
parent epic. Browser-QA remains on retained operator-debug reads; epic
simulation and dispatch-chain reads use the registered
`yoke workflow-item ...` wrappers below.

