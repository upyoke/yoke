# Usher — resolve generated task merge

The caller has selected this internal procedure from the parent's pinned
child and worktree policies. Resolve the supplied public or project-local
reference through the registered item reader; the numeric tail is not an
`items.id`.

```bash
_epic_ref="PREFIX-N"
_epic_id=$(yoke items get "$_epic_ref" id) || exit 1
yoke workflows item get "$_epic_ref" --json
yoke epic-tasks list --epic "$_epic_id"
```

Require the effective policies to declare `generated_children=epic_tasks`
and `worktrees=worker_and_integration_lanes`; otherwise stop with
`generated_task_merge_policy_mismatch` and return to the caller's policy
selection in [merge.md](merge.md). Do not infer the route from a workflow name.

If no task rows exist, stop with `generated_task_merge_tasks_missing`:
restore the declared task graph before retrying this internal step. A missing
graph is not successful completion.

Retain `_epic_ref` and `_epic_id` for the following phases.
Next: [merge preflight](merge-preflight.md).
