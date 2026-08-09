---
name: plan
description: Invoke the Architect subagent to produce the plan shape selected by the item's pinned workflow policies.
argument-hint: "{item-id}"
---

# Internal sub-skill — called by the skill that owns plan authoring.

# /yoke plan {item-id}

Translate an item spec into a technical implementation plan. The item's
immutable workflow pin selects whether planning writes one item-level
`technical_plan` or a persisted generated-task decomposition.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `{item-id}` — A `PREFIX-N` reference, internal numeric item id, or lowercase
  title slug with spaces replaced by `-`.

## Authority

Never choose plan mode from `workflow_id`. Resolve the exact item pin with
`workflows.item.get`, read its logical version with `workflows.version.get`,
and interpret:

- ordered `stages` plus half-open `skill_bindings` for the current owner;
- `policies.generated_children` for decomposition storage;
- `policies.worktrees` for lane planning;
- stage gate ids for simulation requirements.

Skill names remain valid guards because this sub-skill is an implementation
detail of those registered skills. Workflow names are registry keys, not
behavior branches.

## Steps

### 1. Resolve the item and immutable definition

Stamp the session, then resolve numeric or public references:

```bash
yoke sessions touch --mode plan
_plan_item_ref="{item-id}"
_plan_pin_json=$(yoke workflows item get "$_plan_item_ref" --json 2>/dev/null) || _plan_pin_json=""
```

If the read fails because the input is a title slug, list all visible items in
one registered collection read:

```bash
yoke items list \
 --fields "id,project_sequence,title,workflow_id,workflow_version_id,status" \
 --limit 1000
```

Match the normalized title, set `_plan_item_ref=PREFIX-{project_sequence}`, and
repeat `workflows.item.get`. Do not filter the fallback by remembered workflow
names and do not treat `project_sequence` as `items.id`.

Extract `item_id`, `workflow_id`, logical `workflow_version`, and `status` from
the pin:

```bash
_plan_item_id=$(printf '%s' "$_plan_pin_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["item_id"])')
_plan_workflow_id=$(printf '%s' "$_plan_pin_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["workflow_id"])')
_plan_workflow_version=$(printf '%s' "$_plan_pin_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["workflow_version"])')
_plan_status=$(printf '%s' "$_plan_pin_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["status"])')
```

Read the exact definition:

```bash
_plan_definition_json=$(yoke workflows version get \
 "$_plan_workflow_id" "$_plan_workflow_version" --json) || {
 echo "Pinned workflow $_plan_workflow_id@$_plan_workflow_version is unavailable."
 exit 1
}
```

Interpret the current skill with the runtime interval
`from_stage_id <= current < through_stage_id`. Extract
`generated_children` and `worktrees` from `definition.policies`.

Select mode:

- `generated_children=none` → `_plan_mode=item_plan`.
- `generated_children=epic_tasks` → `_plan_mode=task_graph`.
- Any other value → halt as unsupported; do not guess a storage shape.

Apply the skill guard:

- `item_plan` is authored only while the pinned current skill is `advance`.
- `task_graph` is authored only while the pinned current skill is
  `shepherd`.
- Otherwise stop and route to the skill returned by the definition. In
  particular, do not re-plan after the item has crossed into a `refine`,
  `conduct`, `polish`, or `usher` segment.

Use `_plan_item_ref` for item calls and the normalized numeric `_plan_item_id`
for `epic_tasks.epic_id`.

### 2. Validate the planning input

Run the registered PRD validator for both modes:

```bash
yoke readiness prd-validate "$_plan_item_ref"
```

- Exit 1: stop and present the report. Do not dispatch the Architect.
- Exit 0 with warnings: present them and ask for confirmation because unresolved
  questions can change interfaces, files, or task boundaries.

Read the authoritative spec and optional design input through registered item
reads. Do not plan from cached body text:

```bash
yoke items get "$_plan_item_ref" spec
yoke items get "$_plan_item_ref" design_spec
```

### 3. Reconcile existing generated tasks

Skip this step for `item_plan`.

For `task_graph`, read persisted rows:

```bash
yoke epic-tasks list --epic "$_plan_item_id"
```

- Any task beyond planning-owned stages: stop; re-planning active work is not
  supported.
- Only planning-owned rows: ask **Resume** or **Restart**.
  - Resume: retain the rows and continue at the review step.
  - Restart: remove each row through
    `yoke workflow-item epic-task remove --epic "$_plan_item_id" --task-num N
    --reason "plan restart"`, then continue.
- No rows: continue.

The `epic_tasks` name and its `epic_id` column are persisted domain contracts;
using them does not imply a workflow-name branch.

### 4. Survey the codebase

Use the Explore subagent to inspect:

- current architecture and reusable surfaces;
- affected modules and file sizes;
- test frameworks and representative tests;
- project documentation;
- active path claims or in-flight work touching the same files.

Ground every proposed path and symbol in the live checkout. When the Explorer
queries task data, teach the verified physical columns:
`epic_tasks.epic_id`, `task_num`, and `dependencies`.

### 5. Dispatch the Architect

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

### 6. Persist the plan

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

### 7. Present and hand back to the owning skill

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

### 8. Simulation recommendation

Inspect all served stage gates. If any gate id is `plan_simulation`, recommend
`/yoke simulate {_plan_item_ref}` before the implementation skill runs.
Otherwise simulation is not required by this definition.

## Review checklist

- Technical approach is implementable without guessing.
- Edge cases and recovery paths are explicit.
- Verification steps are concrete.
- Reuse, quality, efficiency, and future-concept lenses are applied.
- In `task_graph` mode, task sizes, interfaces, dependencies, file budgets,
  and lane assignments are safe and complete.
