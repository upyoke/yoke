# Conduct — Engineer prompt and Tester diffs

Spawn `yoke-engineer` ([role spawn](../shared/role-spawn.md)); no isolation. One per task:

```text
Implement PREFIX-{N} task {_task_id}: {task title}
Parent: {_epic_ref}; project: {PROJECT}; GitHub issue: {github_issue}
Registered lane: {WORKTREE_PATH}; branch: {BRANCH}; main owner: {MAIN_ROOT}
yoke workflow-item epic-task body-get --epic {_epic_ref} --task-num {_task_id}
yoke items get PREFIX-{N} spec
Before the first edit, read {WORKTREE_PATH}/.yoke/docs/agents/rules/index.md
and code-and-cli.md, then each home the index names before its operation.
```

Add dependency interfaces, project docs, QA roster, preview URL, prior
attempts, any persisted `## Anticipated Paths` and retry feedback. Live state is READ-ONLY unless an
AC says APPLY-MUTATION. Require the SUBMISSION-CHECKS progress note.

Tester diffs: `git -C {WORKTREE_PATH} diff {TASK_BASELINE}..HEAD` (and
`{ATTEMPT_BASELINE}..HEAD` on retries). Inline up to 300 lines; above that pass
`--stat` and the capture path. Render
[the shared Tester template](../shared/tester-dispatch-template.md).
