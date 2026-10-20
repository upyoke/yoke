# Tester dispatch template

Render `DispatchDescriptor(role="tester")`; a task uses its own lane.

```text
Validate {public_ref}{ task {task_num}}: {title}
Spec: {spec}
Review identity: epic-id: {epic_ref} task-num: {task_num}
Cases: {qa requirement rows or "none attached"}
Worktree: {worktree_path}  Changed: {changed_files}  Diff: {diff up to 300 lines, else capture path}
Check every acceptance criterion; compare failing test names on main and branch.
Task only: yoke workflow-item epic-task review-insert --epic {epic_ref} --task-num {task_num} --verdict <pass|fail> --head-sha {REVIEWED_HEAD_SHA} --body-file <review-path>
End with VERDICT: PASS or VERDICT: FAIL.
```
