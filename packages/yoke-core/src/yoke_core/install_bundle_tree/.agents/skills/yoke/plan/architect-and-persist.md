# /yoke plan steps 5–8 — dispatch the Architect, persist, hand back

## 5. Dispatch the Architect

Pass:

- `_plan_item_ref`; the Architect reads the authoritative spec with
  `yoke items get ... spec`;
- the optional design spec;
- the surveyed code and documentation context;
- the served planning mode and policies, not a workflow name.

Output contract:

- `item_plan`: one `## Technical Plan` covering approach, decisions, edge
  cases, and test strategy. No child rows or worktree plan.
- `task_graph`: `## Technical Plan`, one complete body per generated task, and
  `## Worktree Plan` consistent with the served lane policy.

Capture any delimited Architect Ouroboros entries with
`yoke ouroboros entry insert --agent architect --context "plan {item-id}" ...`.

## 6. Persist the plan

For both modes, dispatch `items.structured_field.replace` for
`technical_plan`.

For `item_plan`, stop there:

- do not write `worktree_plan`;
- do not write `epic_tasks` or `epic_task_files`;
- do not mutate lifecycle status.

For `task_graph`:

1. Add each task with `workflow_item.epic_task.add`, targeting
   `{kind: "epic_task", epic_id: _plan_item_id, task_num: N}` and supplying
   `title`, complete `body`, worktree assignment, `context_estimate`, and
   dependencies.
2. Add each file through `yoke workflow-item epic-task file-add --epic
   "$_plan_item_id" --task-num N --file-path PATH --action
   create|modify|delete`.
3. Dispatch `items.structured_field.replace` for `worktree_plan`.

All plan data is DB-backed. Do not create filesystem plan artifacts or invent
another child table.

## 7. Present and hand back to the owning skill

Present the generated content and ask for explicit confirmation.

- `item_plan`: show `technical_plan`.
- `task_graph`: show the task table, worktree plan, dependency interfaces, and
  any large tasks. Use `yoke workflow-item epic-task body-get --epic
  "$_plan_item_id" --task-num N` for deep review.

If rejected, leave item status unchanged. For `task_graph`, remove planning
rows created by this attempt through the registered task owner.

If accepted, leave lifecycle transition to the registered caller:

- `advance` consumes the item-level plan and owns implementation entry.
- `shepherd` runs its plan-quality gate and owns its binding handoff; the
  subsequent pinned skill performs any plan-refinement segment.

Plan must never jump directly to a remembered status such as `planned`.

## 8. Simulation recommendation

Inspect all served stage gates. If any gate id is `plan_simulation`, recommend
`/yoke simulate {_plan_item_ref}` before the implementation skill runs.
Otherwise simulation is not required by this definition.

