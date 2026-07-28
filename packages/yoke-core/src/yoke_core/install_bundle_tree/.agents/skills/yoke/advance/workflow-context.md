# Advance — Pinned Workflow Context

Called by `SKILL.md` before target resolution. Read the item's immutable pin,
exact definition, policy shape, and current executor:

```bash
_item_workflow_json=$(yoke workflows item get YOK-{N} --json) || {
 echo "Item YOK-{N} not found."
 exit 1
}
_workflow_id=$(printf '%s' "$_item_workflow_json" | python3 -c 'import json,sys
print(json.load(sys.stdin)["result"]["workflow_id"])')
_workflow_version=$(printf '%s' "$_item_workflow_json" | python3 -c 'import json,sys
print(json.load(sys.stdin)["result"]["workflow_version"])')
_status=$(printf '%s' "$_item_workflow_json" | python3 -c 'import json,sys
print(json.load(sys.stdin)["result"]["status"])')
_title=$(yoke items get {N} title)
_pinned_definition_json=$(yoke workflows version get "$_workflow_id" "$_workflow_version" --json) || {
 echo "The pinned workflow version $_workflow_id@$_workflow_version could not be read."
 exit 1
}
_generated_children=$(printf '%s' "$_pinned_definition_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["definition"]["policies"]["generated_children"])')
_worktree_policy=$(printf '%s' "$_pinned_definition_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["definition"]["policies"]["worktrees"])')
_parallelism_policy=$(printf '%s' "$_pinned_definition_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["definition"]["policies"]["parallelism"])')
_current_executor=$(printf '%s' "$_pinned_definition_json" | python3 -c '
import json,sys
status=sys.argv[1]
definition=json.load(sys.stdin)["result"]["definition"]
stages=[stage["id"] for stage in definition["stages"]]
position=stages.index(status)
for binding in definition["executor_bindings"]:
    start=stages.index(binding["from_stage_id"])
    stop=stages.index(binding["through_stage_id"])
    if start <= position < stop:
        print(binding["executor_id"])
        break
' "$_status")
```

The executor interpreter uses the runtime's half-open interval
(`from_stage_id <= current < through_stage_id`). `workflow_id` is only the
registry key for the exact version read; no behavior branches on its value.
