# /yoke amend — the amend sequence

1. **Verify the item has epic tasks.** Read via the
   `epic_tasks.list.run` function call (`target = {kind: "epic_task",
   epic_id: <id>}`, empty payload). If `result.tasks` is empty, inform
   the user and suggest next steps:

   > PREFIX-{epic-id} has no epic tasks. Run `/yoke plan PREFIX-{epic-id}`
   > to create tasks first, then retry `/yoke amend`.

   Do NOT conclude from an empty result that the item is "not an epic"
   — it may simply need `/yoke plan` first. Do NOT fall back to
   directly editing the item body as a workaround.

2. **Show current task state.** Render the `epic_tasks.list.run`
   response as a readable table with one row per task (task_num,
   title, worktree, context_estimate, dependencies, status,
   dispatch_attempts).

3. **Check for simulation gaps.** Query simulation reports through the
   registered epic-task read wrapper:

   ```bash
   yoke workflow-item epic-task simulation-get --epic "{epic-id}" --phase integration
   ```

   Fall back to `plan` if no integration report exists. If a report
   has gaps:

   - Parse the `## Gaps Found` section for each `### GAP #N` entry.
   - Filter to gaps with severity `[WARNING]` or `[CRITICAL]`
     (include `[NOTE]` gaps when they have concrete fix guidance).
   - Present a summary to the user:

     > **Simulation report found {N} gaps with fix guidance:**
     > - GAP #1 [SEVERITY]: {one-line summary}
     > - GAP #2 [SEVERITY]: {one-line summary}
     >
     > **Recommended:** Create a single fix task covering all
     > actionable gaps.

   - If the user confirms, skip step 4's "gather task details" —
     auto-generate the task: title `"Fix integration simulation gaps
     (GAP #1-#N)"`, body composed of each gap's root cause + fix
     guidance, ACs one per gap, files-touched derived from each gap's
     fix guidance.

   If no simulation report exists or it has no gaps, proceed to step 4.

4. **Ask what the user wants to do** (skip if step 3 already
   determined the action):

   - **Add** a new task
   - **Split** an existing task into smaller tasks
   - **Reassign** a task to a different worktree
   - **Remove** a task (only at `planning` / `planned`)

5. **For adding a task** (including simulation-gap tasks from step 3),
   dispatch the `workflow_item.epic_task.add` function call (envelope
   in [`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)):

   - `target = {kind: "epic_task", epic_id: <id>, task_num: <next>}`
     where `<next>` is `MAX(task_num) + 1` from the prior
     `epic_tasks.list.run` response.
   - `payload = {title, body, worktree, context_estimate, dependencies}`.

   The handler mints the row, history record, and starts at `planning`.
   Then assign the new task's GitHub issue number via
   `workflow_item.epic_task.metadata_update` once the REST
   issue-create step lands the issue id (`payload.fields =
   {"github_issue": "<number>"}`). After the metadata write, dispatch
   `lifecycle.transition.execute` against the same task to advance to
   `planned` if you want to skip the `planning` review step.

   Finally, refresh the parent epic's `worktree_plan` via
   `items.structured_field.replace` (`target = {kind: "item", item_id:
   <epic-id>}`, `payload = {field: "worktree_plan", content:
   "<updated worktree plan>", source: "amend"}`) so the new task id
   appears in the rendered plan.

6. **For splitting a task**, dispatch
   `workflow_item.epic_task.split` with `target = {kind: "epic_task",
   epic_id, task_num: <parent>}` and `payload = {children: [{title,
   body, worktree, context_estimate, dependencies}, ...]}`. The
   handler mints each child task row, rewrites dependencies that
   pointed at the parent task to point at the children, and marks
   the parent task `replaced`. Create the GitHub issues for each
   child afterwards, then update each child's `github_issue` via
   `workflow_item.epic_task.metadata_update`.

7. **For reassigning a worktree**, dispatch
   `workflow_item.epic_task.reassign` with `target = {kind:
   "epic_task", epic_id, task_num}` and `payload = {new_worktree:
   "<path>"}`. The handler updates the task row and emits the
   matching audit event. Refresh the parent epic's `worktree_plan`
   via `items.structured_field.replace` afterwards, and update any
   GitHub issue labels that reference worktree names.

8. **For removing a task**, dispatch `workflow_item.epic_task.remove`
   with `target = {kind: "epic_task", epic_id, task_num}` and
   `payload = {reason: "<why the task is no longer needed>"}`. The
   handler refuses tasks that are not at `planning` / `planned`;
   in-progress or completed tasks must be retired through a
   different path (typically by routing through `/yoke wrapup`).
   The handler also cascades dependency rewrites (other tasks that
   depended on this one are updated). Close the GitHub issue
   afterwards.

9. **Re-verify file overlap.** Read the refreshed task list and file
   assignments via `yoke epic-tasks list --epic "{epic-id}"`. Check for
   duplicate file paths across different
   worktrees. If overlap is detected, warn the user and help
   reassign files via `workflow_item.epic_task.reassign` or
   `metadata_update`.

10. **Create any missing worktrees.** If the worktree plan now
    references worktrees that don't exist yet, create them. Query
    dispatch chains via `yoke workflow-item epic-dispatch-chain list
    --epic "{epic-id}"` to find worktree paths.

11. **Update dispatch chain (if one exists).** Read the chain via the
    registered dispatch-chain wrapper:

    ```bash
    yoke workflow-item epic-dispatch-chain get --epic "{epic-id}" --worktree "{worktree}"
    ```

    If a chain exists and a new task was added to that worktree,
    extend the chain queue:

    ```bash
    yoke workflow-item epic-dispatch-chain update --epic "{epic-id}" --worktree "{worktree}" --field queue --value "{updated_queue_json}"
    ```

    If no dispatch chain exists for the worktree, skip — one will be
    created when `/yoke conduct` is first run.

## Notes

- This command modifies state. Don't run it while a dispatch is in
  progress for the same epic.
- File overlap is re-verified after every change. This is the safety
  net.
- New tasks created via amend get new GitHub issue numbers, following
  the same pattern as sync.
- All workflow-item task data (titles, bodies, statuses, dependencies)
  flows through the `workflow_item.epic_task.*` function family.
  Simulation and dispatch-chain reads/writes flow through
  `yoke workflow-item epic-task simulation-get` and
  `yoke workflow-item epic-dispatch-chain ...`; `db_router query`
  remains the retained operator-debug surface for ad hoc SQL/counts.
