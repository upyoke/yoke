# /yoke implement phase 1 — resolve the pin, then enter or re-enter

Keep the operator's token as the public item ref. Never treat the numeric tail
of `PREFIX-N` as `items.id`.

## Resolve the pinned segment

`workflows.item.get` serves the item's immutable pin and its effective
policies; the exact version read serves the definition this skill interprets:

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

`_segment` is `<skill> <from_stage_id> <through_stage_id>` for the binding whose
half-open interval (`from_stage_id <= live stage < through_stage_id`) contains
the live stage. `workflow_id` is only the registry key for the version read; no
behavior branches on its value. File Budget and path claims are independent
effective axes read only from `result.effective_policies`; the 350-line
authored-file limit remains universal.

## Require the implement binding

- The bound skill must be `implement`. When another skill is bound at the live
  stage, stop and report the item, its live stage, and that bound skill; do
  not transition toward this segment from here.
- `_worktree_policy` must be `single_implementation_lane`, or `none` for a
  laneless workflow where the work happens in place. Any multi-lane policy
  belongs to the task-graph skill its binding names; stop and report it.

## Reach the binding's entry stage first

Implementation entry is valid only from the `implement` binding's
`from_stage_id` under `single_implementation_lane` or `none`. The engine
dispatches the single adjacent `lifecycle.transition.execute` from that stage;
it does not walk earlier stages. An item still before that stage gets there
through the skill bound at its live stage (`/yoke refine` owns an active refine
segment), or through `/yoke advance PREFIX-N --skip-refine` when refine
deliberation is unnecessary. Never hand-write intermediate status writes to
climb toward the entry stage: raw status writes are claim-protected and refused
with `ClaimVerificationDenied`.

## Enter at the binding's entry stage

When the live stage equals the binding's `from_stage_id`, enter through the
engine. Defer the first work-claim acquisition to the orchestrator: its
identity probe must pass before
`worktree_preflight.run_preflight` acquires the claim and creates the lane, so
do not acquire one first:

```bash
yoke advance implementation-entry --item PREFIX-N
```

Pass through `--no-worktree` (evidence-only work, see
[`evidence-only.md`](evidence-only.md)), `--force` (operator-asserted override
of the file-level collision blocker and generated-task gates), or
`--qa-bypass` when the invocation carried them; `--help` prints the matrix. A
`none` worktree policy skips lane creation on its own, so `--no-worktree` is
neither needed nor meaningful there.

The engine composes preflight gates → `worktree_preflight.run_preflight`
(claim + path-claim activation + worktree creation or reuse) → the
capability-gated environment phase → the single adjacent
`lifecycle.transition.execute` into the next stage, inside one Python process,
emitting one `AdvancePhaseCompleted` event per phase. Its preflight retains
activation dependencies and applies File Budget and spec coverage only as the
effective policies select them; acceptance criteria are a Refine-closure check
(`readiness.check.run`), not an implementation-entry gate. It is idempotent:
rerunning against an item already in that stage reuses the worktree,
re-acquires the same claim, and skips the status write. A preflight failure
stops before any claim or lane mutation and prints the gate narrative;
`worktree-create-failed` releases the claim; a finalize failure leaves the
worktree and claim in place so the next invocation converges. Verify the trail
with `yoke events query --item PREFIX-N --event-name AdvancePhaseCompleted`.

Before any claim or lane mutation the engine corroborates the acting session
through the ambient resolver the write guards use. Missing identity refuses as
`write-guard-identity-unresolved`; an explicit `--session-id` must match the ambient result. Repair the harness env stamp, process-anchor registry, or Cursor
conversation map and retry — never provision an unwritable lane with a guessed
identity.

A sanctioned block (`work-claim-conflict`, `path-claim-blocked`,
`upstream-unverified`, `upstream-stale`, dirty trees,
`worktree-create-failed`) is surfaced verbatim and stops the skill; do not
retry it with `--force` or paper over it by widening a claim.

On success, read the registered lane path into `WORKTREE_PATH` and continue in
this session with [`implementing/SKILL.md`](implementing/SKILL.md):

```bash
WORKTREE_PATH=$(yoke item-worktrees get PREFIX-N --lane-role implementation --field path)
```

Under a `none` policy leave `WORKTREE_PATH` empty.

## Re-enter past the entry stage

When the live stage is past `from_stage_id` but still inside the segment, the
lane already exists. Take the claim first —
`yoke claims work acquire --item PREFIX-N --reason implement-reentry` is
idempotent for the same session and refuses with `claim_conflict` naming the
holder when another live session owns the item, which stops the skill — then
follow [`reentry.md`](reentry.md).

Claims persist across idle sweeps, process exit, and restart; Stop and
SessionEnd hooks never release them. The release at the binding's handoff is
owned by [`review.md`](review.md).
