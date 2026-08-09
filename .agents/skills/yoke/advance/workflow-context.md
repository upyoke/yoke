# Advance — Pinned Workflow Context

Called by `SKILL.md` before target resolution. Registered
`workflows.item.get` supplies the item's immutable pin and central effective
policies; read the exact definition separately for skill interpretation:

```bash
_item_workflow_json=$(yoke workflows item get PREFIX-{N} --json) || {
 echo "Item PREFIX-{N} not found."
 exit 1
}
_workflow_id=$(printf '%s' "$_item_workflow_json" | python3 -c 'import json,sys
print(json.load(sys.stdin)["result"]["workflow_id"])')
_workflow_version=$(printf '%s' "$_item_workflow_json" | python3 -c 'import json,sys
print(json.load(sys.stdin)["result"]["workflow_version"])')
_status=$(printf '%s' "$_item_workflow_json" | python3 -c 'import json,sys
print(json.load(sys.stdin)["result"]["status"])')
_effective_file_budget_policy=$(printf '%s' "$_item_workflow_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["effective_policies"]["file_budget"])')
_effective_path_claims_policy=$(printf '%s' "$_item_workflow_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["effective_policies"]["path_claims"])')
_title=$(yoke items get {N} title)
_pinned_definition_json=$(yoke workflows version get "$_workflow_id" "$_workflow_version" --json) || {
 echo "The pinned workflow version $_workflow_id@$_workflow_version could not be read."
 exit 1
}
_generated_children=$(printf '%s' "$_pinned_definition_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["definition"]["policies"]["generated_children"])')
_worktree_policy=$(printf '%s' "$_pinned_definition_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["definition"]["policies"]["worktrees"])')
_current_skill=$(printf '%s' "$_pinned_definition_json" | python3 -c '
import json,sys
status=sys.argv[1]
definition=json.load(sys.stdin)["result"]["definition"]
stages=[stage["id"] for stage in definition["stages"]]
position=stages.index(status)
for binding in definition["skill_bindings"]:
    start=stages.index(binding["from_stage_id"])
    stop=stages.index(binding["through_stage_id"])
    if start <= position < stop:
        print(binding["skill_id"])
        break
' "$_status")
```

The skill interpreter uses the runtime's half-open interval
(`from_stage_id <= current < through_stage_id`). `workflow_id` is only the
registry key for the exact version read; no behavior branches on its value.
File Budget and path claims are independent effective axes. `optional` is off
at the applicable scope; `required` and `required_per_task` are on at their
item and generated-task scopes. These values come only from
`result.effective_policies` so historical schema compatibility and allowed
posture tightening remain runtime-owned. The 350-line authored-file limit
remains universal in every combination.
