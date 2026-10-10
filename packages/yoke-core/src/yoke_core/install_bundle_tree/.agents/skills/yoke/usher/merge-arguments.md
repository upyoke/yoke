# Usher — resolve generated-task merge

Internal route selected by effective generated_children=epic_tasks and
worktrees=worker_and_integration_lanes, never workflow name. Hold parent claim
and carry the supplied complete public ref unchanged; numeric tail is not id.

```text
yoke workflows item get PREFIX-N --json
yoke epic-tasks list --epic PREFIX-N --json
yoke item-worktrees list PREFIX-N --json
```

Mismatched policies refuse generated_task_merge_policy_mismatch and return to
merge's policy selection. Empty graph refuses generated_task_merge_tasks_missing;
restore its declared graph, don't pretend completed. Registered lane paths and
branches own file access; no constructed .worktrees paths or borrowed project.
Continue to [preflight](merge-preflight.md).
