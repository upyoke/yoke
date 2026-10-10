# Amend — Typed Surfaces

Read [common envelopes](../idea/body-and-sync-functions.md) and
[task catalog](../../../../.yoke/docs/reference/db-reference/functions-tasks.md)
before calling an operation.

Task mutations:
`workflow_item.epic_task.add`, `body_replace`, `split`, `reassign`,
`remove`, `metadata_update`. Use `metadata_update` for scalar fields such as
github_issue/dependencies. [steps.md](steps.md) owns their action payloads.
Parent worktree_plan writes use `items.structured_field.replace`.

Simulation and dispatch-chain reads/writes use registered
`yoke workflow-item epic-task simulation-get` and
`yoke workflow-item epic-dispatch-chain ...`.

Resolve/create registered lanes through
[worktree catalog](../../../../.yoke/docs/reference/db-reference/functions-worktrees.md);
preserve policy-required roles, verified-current upstream, work/path claims,
absolute path recording and stale-state preconditions. Browser QA retains its
existing operator-debug reads.
