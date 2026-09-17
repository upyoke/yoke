# /yoke plan steps 1–4 — resolve the pin, validate input, reconcile tasks, survey

## 1. Resolve the item and immutable definition

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

## 2. Validate the planning input

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

## 3. Reconcile existing generated tasks

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

## 4. Survey the codebase

Use the Explore subagent to inspect:

- current architecture and reusable surfaces;
- affected modules and file sizes;
- test frameworks and representative tests;
- project documentation;
- active path claims or in-flight work touching the same files.

Ground every proposed path and symbol in the live checkout. When the Explorer
queries task data, teach the verified physical columns:
`epic_tasks.epic_id`, `task_num`, and `dependencies`.


Next: [`architect-and-persist.md`](architect-and-persist.md).
