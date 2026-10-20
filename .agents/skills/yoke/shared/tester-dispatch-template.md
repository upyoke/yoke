# Tester dispatch template

Spawn `yoke-tester` ([role spawn](role-spawn.md)); a task uses its own lane.

```text
Validate {public_ref}{ task {task_num}}: {title}
Spec: {spec}
Review identity: epic-id: {epic_ref} task-num: {task_num}
Cases: {qa requirement rows or "none attached"}
Run them: yoke qa plan run --item {public_ref} --transition {transition}
On exit 12, execute the returned review dispatch and its submit command now.
Test commands: {resolved Quick/Full/E2E/Smoke}  Preview URL: {healthy url from `yoke ephemeral-env get PROJECT BRANCH --json`, else none}
Worktree: {worktree_path}  Changed: {changed_files}  Diff: {diff up to 300 lines, else capture path}
{minimal retry: no inline diff; read the changed files and return a verdict}
Check every acceptance criterion; compare failing test names on main and branch.
Task only: before reviewing, record REVIEWED_HEAD_SHA as the full HEAD of the clean task lane, then persist with yoke workflow-item epic-task review-insert --epic {epic_ref} --task-num {task_num} --verdict <pass|fail> --head-sha {REVIEWED_HEAD_SHA} --body-file <review-path>
End with VERDICT: PASS or VERDICT: FAIL.
```
