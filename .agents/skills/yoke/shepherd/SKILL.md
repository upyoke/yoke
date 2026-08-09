---
name: shepherd
description: "Execute a pinned Shepherd planning segment through its quality gates"
argument-hint: "{PREFIX-N}"
---

# /yoke shepherd {PREFIX-N}

Execute the `shepherd` segment registered by the item's immutable workflow
version, applying Boss quality gates at every transition. Each step is: Worker
produces artifact -> Boss reviews -> persist verdict -> advance or retry.

Shepherd is selected by an active `skill_bindings` interval, not by an item
type or workflow id. This implementation supports the generated-task planning
contract (`generated_children=epic_tasks`) and verifies the exact pinned
segment before it writes anything.

> Standalone mode (`/yoke shepherd PREFIX-N`) is the primary usage. The `--subagent` mode is retained for backward compatibility and potential future use.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `{PREFIX-N}` -- Backlog item ID. Accepts prefixed IDs, zero-padded prefixed IDs, or bare numeric IDs.
- `--subagent --session <id>` -- Run in subagent mode (no user interaction, auto-advance, exit 1 on failure).

## Constants

```text
MAX_ATTEMPTS=3
MAX_SIMULATOR_FIX_CYCLES=2
```

## Structured Field Write Rules

Never use ad-hoc body surgery. The item body is a generated view assembled by `python3 -m yoke_core.domain.render_body` from structured DB fields. Shepherd writes to isolated fields such as `shepherd_log` and `shepherd_caveats`, then re-renders the body through the items-update surface. Prefer stdin; use a body file only when you already have a real artifact file.

## Philosophy

**Be the giant.** We stand on inherited shoulders; leave a leg up for the next agent by making this artifact cold-start complete. Each subagent you dispatch starts with zero context. The dispatch prompt is their entire world. Missing context in a dispatch prompt is the #1 cause of low-quality agent output.

**No such thing as "agent error."** When a subagent returns NOT_READY or low-quality output, the cause is systemic: insufficient dispatch context, truncated input, missing instructions, a file too large to read fully (P-50), or "you MUST" rules that failed under context pressure (P-26). Fix the dispatch, not the agent. Log the root cause in Ouroboros reflections.

**Events table for diagnosis.** When investigating why a subagent produced unexpected output, query the events table: `yoke events tail --limit 20`.

## Body Content Isolation Rules

The shepherd must not let item body content pollute its orchestration context.

1. Silent reads only. Read bodies into variables for structural checks; do not echo body content to stdout.
2. Discard after use. Once a body check is done, do not keep reusing the body content in context.
3. Subagents read body content independently from the DB.
4. If body text must appear inline, wrap it in explicit data fences.
5. Re-anchor between transitions so the shepherd stays in orchestrator mode.
6. For session-continuity context that successor agents need to resume after compaction, write to the **Progress Log** section on the task-graph parent item — see `AGENTS.md > Progress Log — long-running execution context on items`. Use this for shepherd-level state (which gates have run, which subagents are dispatched, which open questions remain) rather than `shepherd_log` (which is the structured verdict surface, not an execution scratchpad).

## Steps

### 1. Parse Arguments

Extract the numeric ID from `PREFIX-N` and detect standalone vs subagent mode.

### 2. Read Item

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

### 3. Derive Transitions From The Validated Binding

The supported pinned Shepherd segment yields:
- `refined-idea` -> `refined_idea_to_planning`, `planning_to_plan_drafted`
- `planning` -> `planning_to_plan_drafted`

These transition ids are Shepherd verdict keys for this skill contract.
They are not a global item progression. The next skill at
`_shepherd_through_stage` comes from the pinned definition.

### 4. Resume Logic

Before executing transitions, read prior verdict history:

```bash
_completed=$(yoke db read --format lines "SELECT transition FROM shepherd_verdicts WHERE item='PREFIX-$_num' AND (verdict='READY' OR verdict='CAVEATS' OR verdict='SKIPPED') ORDER BY id")
_blocked=$(yoke db read --format lines "SELECT transition FROM shepherd_verdicts WHERE item='PREFIX-$_num' AND verdict='BLOCKED' ORDER BY id")
```

Rules:
- READY / CAVEATS / SKIPPED -> skip the transition
- BLOCKED -> report and stop
- NOT_READY with attempts remaining -> resume at next attempt
- Otherwise -> execute from attempt 1

If all transitions are already complete, advance the item to
`_shepherd_through_stage` and finish.

### 5. Execute Each Transition

For each remaining transition:

1. Set `_scholar_context=""` (Scholar is still a stub).
2. Gather prior caveats from earlier `CAVEATS` verdicts.
3. Route to the correct transition file:
 - `refined_idea_to_planning` -> [design-and-plan.md](design-and-plan.md)
 - `planning_to_plan_drafted` -> [planning-to-planned-gates.md](planning-to-planned-gates.md), then [boss-verdict.md](boss-verdict.md)
4. After any worker completes, always run [boss-verdict.md](boss-verdict.md) for the review, parsing, persistence, reflection, and retry/result logic.

### 6. Finalize And Report

After each verdict and after the full pipeline completes, read and follow [finalize.md](finalize.md).

That phase owns:
- Shepherd Log rendering and guarded writes
- Transition re-anchoring and auto-continuation
- Progress commits
- Final reporting
- Error handling and DB operations reference
