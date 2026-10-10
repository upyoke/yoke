# Refine — Exact Pinned Context

Read once through registered `workflows.item.get`:
```bash
ITEM_REF="{arg}"
ITEM_PIN_JSON=$(yoke workflows item get "$ITEM_REF" --json)
# ITEM_REF — public PREFIX-N for every item argument.
yoke items get "$ITEM_REF" title
yoke items get "$ITEM_REF" project
ITEM_DEFINITION_JSON=$(yoke workflows version get "$ITEM_WORKFLOW_ID" "$ITEM_WORKFLOW_VERSION" --json)
```

Before the last command, take ITEM_WORKFLOW_ID, ITEM_WORKFLOW_VERSION and
ITEM_STATUS from that pin. Never substitute the registry's current version or
parse a numeric tail/global id. Empty, malformed or failed reads halt with
the actual error. Retain title/project and independent effective values
ITEM_FILE_BUDGET_POLICY and ITEM_PATH_CLAIMS_POLICY from
`result.effective_policies`, not raw policy or posture. Optional is off;
required and required_per_task apply at their reported scopes.

Interpret the returned definition and status:
```bash
REFINE_CONTEXT_JSON=$(printf '%s' "$ITEM_DEFINITION_JSON" | python3 -c '
import json,sys
status=sys.argv[1]
definition=json.load(sys.stdin)["result"]["definition"]
stages=[stage["id"] for stage in definition["stages"]]
position=stages.index(status)
matches=[]
for binding in definition["skill_bindings"]:
    start=stages.index(binding["from_stage_id"])
    stop=stages.index(binding["through_stage_id"])
    if binding["skill_id"] == "refine" and start <= position < stop:
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
        row["skill_id"] == "shepherd"
        and row["through_stage_id"] == binding["from_stage_id"]
        for row in definition["skill_bindings"]
    )
)
next_skill=""
for row in definition["skill_bindings"]:
    row_start=stages.index(row["from_stage_id"])
    row_stop=stages.index(row["through_stage_id"])
    if row_start <= stop < row_stop:
        next_skill=row["skill_id"]
        break
print(json.dumps({
    "source_status": binding["from_stage_id"],
    "active_status": stages[start + 1],
    "target_status": binding["through_stage_id"],
    "artifact_scope": "generated_task_plan" if task_plan else "item_artifact",
    "generated_children": policies["generated_children"],
    "worktrees": policies["worktrees"],
    "next_skill": next_skill,
}))
' "$ITEM_STATUS") || {
 echo "Cannot refine PREFIX-N: the current stage is not supported by its pinned refine binding."
 exit 1
}
```

The interpreter uses ordered stages and the half-open interval. It requires
exactly one refine binding with one active stage, and selects generated-task
scope only for epic_tasks with a Shepherd binding ending at this entry.
No workflow-id branch is allowed. Retain source_status, active_status,
target_status as REFINE_SOURCE_STATUS, REFINE_ACTIVE_STATUS,
REFINE_TARGET_STATUS; artifact_scope as REFINE_ARTIFACT_SCOPE, generated_children
as ITEM_GENERATED_CHILDREN, worktrees policy and next_skill as ITEM_NEXT_SKILL.
The next-skill value must be refreshed after advancement, not carried to handoff.
