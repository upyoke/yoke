# Refine — Pinned Workflow Context

Called by `SKILL.md` before claim acquisition. Registered
`workflows.item.get` resolves the immutable item pin and central effective
policies; the exact definition supplies the active `refine` binding and
child/lane policies.

```bash
MAIN_ROOT=$(git rev-parse --show-toplevel)
ITEM_REF="{arg}"
ITEM_PIN_JSON=$(yoke workflows item get "$ITEM_REF" --json 2>/dev/null) || ITEM_PIN_JSON=""
ITEM_NUM=$(printf '%s' "$ITEM_PIN_JSON" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["item_id"])' 2>/dev/null) || ITEM_NUM=""
ITEM_WORKFLOW_ID=$(printf '%s' "$ITEM_PIN_JSON" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["workflow_id"])' 2>/dev/null) || ITEM_WORKFLOW_ID=""
ITEM_WORKFLOW_VERSION=$(printf '%s' "$ITEM_PIN_JSON" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["workflow_version"])' 2>/dev/null) || ITEM_WORKFLOW_VERSION=""
ITEM_STATUS=$(printf '%s' "$ITEM_PIN_JSON" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["status"])' 2>/dev/null) || ITEM_STATUS=""
ITEM_FILE_BUDGET_POLICY=$(printf '%s' "$ITEM_PIN_JSON" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["effective_policies"]["file_budget"])' 2>/dev/null) || ITEM_FILE_BUDGET_POLICY=""
ITEM_PATH_CLAIMS_POLICY=$(printf '%s' "$ITEM_PIN_JSON" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["effective_policies"]["path_claims"])' 2>/dev/null) || ITEM_PATH_CLAIMS_POLICY=""
ITEM_TITLE=$(yoke items get "$ITEM_REF" title 2>/dev/null) || ITEM_TITLE=""
ITEM_PROJECT=$(yoke items get "$ITEM_REF" project 2>/dev/null) || ITEM_PROJECT=""
ITEM_DEFINITION_JSON=$(yoke workflows version get \
 "$ITEM_WORKFLOW_ID" "$ITEM_WORKFLOW_VERSION" --json 2>/dev/null) || ITEM_DEFINITION_JSON=""
```

If any read is empty, stop with `Item PREFIX-{N} not found.` Never substitute the
registry's current version for `ITEM_WORKFLOW_VERSION`.

Interpret the active binding and policy shape in one pass:

```bash
REFINE_CONTEXT_JSON=$(printf '%s' "$ITEM_DEFINITION_JSON" | python3 -c '
import json,sys
status=sys.argv[1]
definition=json.load(sys.stdin)["result"]["definition"]
stages=[stage["id"] for stage in definition["stages"]]
position=stages.index(status)
matches=[]
for binding in definition["executor_bindings"]:
    start=stages.index(binding["from_stage_id"])
    stop=stages.index(binding["through_stage_id"])
    if binding["executor_id"] == "refine" and start <= position < stop:
        matches.append((binding,start,stop))
if len(matches) != 1:
    raise SystemExit("current stage is not owned by exactly one refine binding")
binding,start,stop=matches[0]
if stop - start != 2:
    raise SystemExit("refine binding must contain exactly one in-progress stage")
policies=definition["policies"]
task_plan=(
    policies["generated_children"] == "epic_tasks"
    and any(
        row["executor_id"] == "shepherd"
        and row["through_stage_id"] == binding["from_stage_id"]
        for row in definition["executor_bindings"]
    )
)
next_executor=""
for row in definition["executor_bindings"]:
    row_start=stages.index(row["from_stage_id"])
    row_stop=stages.index(row["through_stage_id"])
    if row_start <= stop < row_stop:
        next_executor=row["executor_id"]
        break
print(json.dumps({
    "source_status": binding["from_stage_id"],
    "active_status": stages[start + 1],
    "target_status": binding["through_stage_id"],
    "artifact_scope": "generated_task_plan" if task_plan else "item_artifact",
    "generated_children": policies["generated_children"],
    "worktrees": policies["worktrees"],
    "parallelism": policies["parallelism"],
    "next_executor": next_executor,
}))
' "$ITEM_STATUS") || {
 echo "Cannot refine PREFIX-{N}: the current stage is not supported by its pinned refine binding."
 exit 1
}
REFINE_SOURCE_STATUS=$(printf '%s' "$REFINE_CONTEXT_JSON" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["source_status"])')
REFINE_ACTIVE_STATUS=$(printf '%s' "$REFINE_CONTEXT_JSON" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["active_status"])')
REFINE_TARGET_STATUS=$(printf '%s' "$REFINE_CONTEXT_JSON" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["target_status"])')
REFINE_ARTIFACT_SCOPE=$(printf '%s' "$REFINE_CONTEXT_JSON" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["artifact_scope"])')
ITEM_GENERATED_CHILDREN=$(printf '%s' "$REFINE_CONTEXT_JSON" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["generated_children"])')
ITEM_NEXT_EXECUTOR=$(printf '%s' "$REFINE_CONTEXT_JSON" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["next_executor"])')
```

The interpreter deliberately uses the runtime's half-open interval
(`from_stage_id <= current < through_stage_id`). `workflow_id` is only the
registry key for the exact version read; no behavior branches on its value.
`ITEM_FILE_BUDGET_POLICY` and `ITEM_PATH_CLAIMS_POLICY` are independent
effective values from `workflows.item.get`. Do not reconstruct them from
the raw definition or posture: historical schema compatibility and allowed
posture tightening belong to the runtime projection. `optional` is off;
`required` and `required_per_task` apply at their reported scopes.
