# /yoke implement — resolve the pin, then enter or re-enter

Keep the complete public ref; its numeric tail is not `items.id`.
Read `workflows.item.get` and the exact `workflows.version.get`:
```bash
_item_workflow_json=$(yoke workflows item get PREFIX-N --json) || {
 echo "Item PREFIX-N not found."
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
_pinned_definition_json=$(yoke workflows version get "$_workflow_id" "$_workflow_version" --json) || {
 echo "The pinned workflow version $_workflow_id@$_workflow_version could not be read."
 exit 1
}
_worktree_policy=$(printf '%s' "$_pinned_definition_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["definition"]["policies"]["worktrees"])')
_segment=$(printf '%s' "$_pinned_definition_json" | python3 -c '
import json,sys
status=sys.argv[1]
definition=json.load(sys.stdin)["result"]["definition"]
stages=[stage["id"] for stage in definition["stages"]]
position=stages.index(status) if status in stages else -1
for binding in definition["skill_bindings"]:
    start=stages.index(binding["from_stage_id"])
    stop=stages.index(binding["through_stage_id"])
    if start <= position < stop:
        print(binding["skill_id"], binding["from_stage_id"], binding["through_stage_id"])
        break
' "$_status")
```


The executable selector uses stage ordering and half-open skill bindings,
never workflow-name branches. File Budget and path claims are independent
`result.effective_policies` axes; 350 authored lines is universal.

Require the live binding to be Implement and worktrees to be
`single_implementation_lane` or `none`. Otherwise report the live stage and
actual bound skill/policy; do not transition toward this segment.

## Preflight policy coverage

Both axes enabled: budget and claims must cover every required file.
Budget off/claims on: claim the execution artifact/survey scope.
Budget on/claims off: budget sizing and conflict evidence remains.
Both off: neither artifact gate applies; the universal limit remains.
Repair missing coverage before edits with `claims.path.widen`, or the
pinned authoring segment's budget repair. Required paths cannot disappear
because another holder claims them; follow dependency and coordination rules.

## Reach the binding's entry stage first

Entry requires the pinned definition's Implement `from_stage_id` and
`single_implementation_lane` or `none`. The engine performs one adjacent
transition, never walks earlier stages. An earlier live stage belongs to its
own pinned binding. Raw intermediate status writes are claim-protected and
refuse with `ClaimVerificationDenied`.

## Enter at the binding's entry stage

Defer the first work-claim acquisition to the orchestrator for ordinary entry:
its identity probe must pass before `worktree_preflight.run_preflight` acquires the claim.
A launch handoff explicitly requiring claim-first takes precedence; the engine
reuses that same-session claim.

```bash
yoke advance implementation-entry --item PREFIX-N
```

Pass only invocation-authorized flags: explicit `--no-worktree`,
`--force` or `--qa-bypass`. Read `--help` for their actual policy matrix;
a `none` policy skips the lane on its own. Never add force to cure a refusal.

The engine composes gates → claim/activation/lane → capability environment →
one adjacent lifecycle transition, emitting `AdvancePhaseCompleted` per phase.
It retains activation dependencies; coverage follows effective axes.
AC completeness is Refine's readiness closure, not an entry gate.
Reentry reuses the lane/claim and skips an already completed status write.

| Result | Required handling |
|---|---|
| Preflight failure | No new claim/lane mutation; surface narrative |
| worktree-create-failed | Engine releases claim; preserve creation error |
| Finalize failure | Lane and claim remain for convergent retry |
| Claim/path conflict, unreadable/stale upstream or dirt | Stop on actual refusal; resolve underlying condition, no force/widen shortcut |

Missing identity refuses `write-guard-identity-unresolved`;
`--session-id` must match the ambient result. Repair harness stamp,
process anchor or conversation map rather than guessing identity.
Verify phase evidence with `yoke events query --item PREFIX-N --event-name AdvancePhaseCompleted`.

On success, recover the registered lane and continue this session:

```bash
WORKTREE_PATH=$(yoke item-worktrees get PREFIX-N --lane-role implementation --field path)
```

For `none`, leave it empty. [Implementing](implementing/SKILL.md) owns the next phase.

## Re-enter past the entry stage

Before lane recovery, acquire the claim:

```text
yoke claims work acquire --item PREFIX-N --reason implement-reentry
```

Same-session acquisition is idempotent. Another live holder's `claim_conflict`
stops reentry. Follow [reentry.md](reentry.md). Claims survive idle, exit and
restart; hooks do not release them. [Review](review.md) owns handoff release.
