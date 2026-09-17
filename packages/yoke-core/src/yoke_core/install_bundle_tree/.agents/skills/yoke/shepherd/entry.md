# /yoke shepherd steps 1–2 — parse the argument and read the item

## 1. Parse Arguments

Extract the numeric ID from `PREFIX-N` and detect standalone vs subagent mode.

## 2. Read Item

Load the immutable item pin and then its exact logical version:

```bash
_num={N}
_item_pin_json=$(yoke workflows item get "PREFIX-$_num" --json) || {
 echo "Item PREFIX-{N} not found."
 exit 1
}
_workflow_id=$(printf '%s' "$_item_pin_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["workflow_id"])')
_workflow_version=$(printf '%s' "$_item_pin_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["workflow_version"])')
_item_status=$(printf '%s' "$_item_pin_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["status"])')
_title=$(yoke items get $_num title)
_pinned_definition_json=$(yoke workflows version get \
 "$_workflow_id" "$_workflow_version" --json) || {
 echo "Pinned workflow $_workflow_id@$_workflow_version is unavailable."
 exit 1
}
```

If any query returns empty, stop with `Item PREFIX-{N} not found.`

Interpret the ordered stages, the unique Shepherd binding, and its policy
contract from that response:

```bash
_shepherd_context_json=$(printf '%s' "$_pinned_definition_json" | python3 -c '
import json,sys
status=sys.argv[1]
definition=json.load(sys.stdin)["result"]["definition"]
stages=[stage["id"] for stage in definition["stages"]]
position=stages.index(status)
bindings=definition["skill_bindings"]
shepherd=[row for row in bindings if row["skill_id"] == "shepherd"]
if len(shepherd) != 1:
    raise SystemExit("definition must contain exactly one shepherd binding")
binding=shepherd[0]
start=stages.index(binding["from_stage_id"])
stop=stages.index(binding["through_stage_id"])
current=""
for row in bindings:
    row_start=stages.index(row["from_stage_id"])
    row_stop=stages.index(row["through_stage_id"])
    if row_start <= position < row_stop:
        current=row["skill_id"]
        break
policies=definition["policies"]
segment=stages[start:stop + 1]
supported=(
    policies["generated_children"] == "epic_tasks"
    and segment == ["refined-idea", "planning", "plan-drafted"]
)
location="before" if position < start else ("after" if position >= stop else "active")
print(json.dumps({
    "current_skill": current,
    "source_stage": binding["from_stage_id"],
    "through_stage": binding["through_stage_id"],
    "path_claims": policies["path_claims"],
    "location": location,
    "supported": supported,
}))
' "$_item_status") || {
 echo "Cannot interpret the pinned Shepherd segment for PREFIX-{N}."
 exit 1
}
_current_skill=$(printf '%s' "$_shepherd_context_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["current_skill"])')
_shepherd_source_stage=$(printf '%s' "$_shepherd_context_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["source_stage"])')
_shepherd_through_stage=$(printf '%s' "$_shepherd_context_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["through_stage"])')
_path_claim_policy=$(printf '%s' "$_shepherd_context_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["path_claims"])')
_shepherd_location=$(printf '%s' "$_shepherd_context_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["location"])')
_shepherd_supported=$(printf '%s' "$_shepherd_context_json" | python3 -c \
 'import json,sys; print(str(json.load(sys.stdin)["supported"]).lower())')
```

If `_shepherd_supported` is not `true`, stop with a contract error: this skill
cannot execute the planning shape published by that pinned version.

If `_shepherd_location` is `after`, stop as a no-op: the item has crossed the
binding's `through_stage_id`. If the location is `before` or
`_current_skill` is not `shepherd`, reject with the current registered
skill and route to `/yoke {_current_skill} PREFIX-{N}`. Never infer that
route from `_workflow_id`.

After validation passes, register the work claim:

```bash
# Session touch + claim
yoke sessions touch --mode shepherd >/dev/null 2>&1 || true
yoke claims work acquire \
 --item "PREFIX-$_num"
```


Next: [`transitions.md`](transitions.md).
