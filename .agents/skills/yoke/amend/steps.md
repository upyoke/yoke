# Amend — Task Changes and Reconciliation

## 1–2. Resolve the graph and show state

Read `epic_tasks.list.run` with target
`{kind: "epic_task", public_ref: "PREFIX-N"}`, empty payload.
No tasks: stop `task_graph_missing`; read
`yoke items detail get PREFIX-N --json` and restore through the pin's
authoring binding. An empty graph does not mean “not an epic” and never
authorizes a direct body-edit workaround.

Show task_num, title, worktree, context_estimate, dependencies, status and
dispatch_attempts. The caller retains its work claim; apply
[surfaces.md](surfaces.md)'s envelopes to every mutation.

## 3–4. Select the approved action

```sh
yoke workflow-item epic-task simulation-get --epic "{epic-ref}" --phase integration
```

Use plan only when no integration report exists. Parse `## Gaps Found` /
`### GAP #N`: critical/warning gaps and notes with concrete fix guidance are
actionable. Summarize severity/guidance and recommend one fix task. On
confirmation derive its title, root-cause/fix body, one AC per gap and touched
files from guidance; skip gathering task details again. Otherwise ask Add,
Split, Reassign or Remove (remove only planning/planned).

## 5–8. Apply one change

All task targets are `{kind: "epic_task", public_ref: "PREFIX-N", task_num}`.

| Action | Registered call and payload | Follow-through |
|---|---|---|
| Add | `workflow_item.epic_task.add`; next task_num = prior MAX + 1; `{title, body, worktree, context_estimate, dependencies}` | New row/history starts planning. Create its GitHub issue, then `metadata_update` with `fields.github_issue`; optionally `lifecycle.transition.execute` to planned to skip planning review. Refresh parent worktree_plan. |
| Split | `workflow_item.epic_task.split`; `{children: [{title, body, worktree, context_estimate, dependencies}, ...]}` | Handler creates children, rewrites parent dependents to them and marks parent replaced. Create each child's issue and record its github_issue. |
| Reassign | `workflow_item.epic_task.reassign`; `{new_worktree: "<path>"}` | Handler updates row/audit. Refresh parent plan and worktree-name issue labels. |
| Remove | `workflow_item.epic_task.remove`; `{reason: "<why>"}` | Only planning/planned; handler rewrites dependencies. Close the issue. In-progress/completed tasks use the ordinary retirement path, typically wrapup. |

Parent plan refresh uses `items.structured_field.replace`, item target with
the complete public ref, payload
`{field: "worktree_plan", content: "<updated full plan>", source: "amend"}`.
Keep the new task id and lane assignment reflected in that authoritative plan.

## 9–11. Reconcile after every change

Read refreshed tasks/file assignments:

```sh
yoke epic-tasks list --epic "{epic-ref}"
yoke workflow-item epic-dispatch-chain list --epic "{epic-ref}"
```

Check duplicate physical files assigned across worktrees. On overlap, warn
and reconcile via task reassign/metadata operations before dispatch. Resolve
missing worktree paths from registered lane/chain authority and create them
through the [worktree surfaces](surfaces.md), with current upstream/path claims.

For each affected worktree:

```sh
yoke workflow-item epic-dispatch-chain get --epic "{epic-ref}" --worktree "{worktree}"
```

An existing chain receiving a task needs its queue extended:

```sh
yoke workflow-item epic-dispatch-chain update --epic "{epic-ref}" --worktree "{worktree}" --field queue --value "{updated_queue_json}"
```

No chain: Conduct creates one at its first run. Re-read receipts/state to verify
the mutation, plan, overlap and queue agree before returning to the caller.
