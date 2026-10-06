# /yoke advance steps 0–2 — skip fast path, parse, target

## 0. Skip-Flag Fast Path

**Run this check before Step 1.** When `--skip-polish` or `--skip-refine` is present in the argument list, the advance skill hands control directly to the canonical skip module and skips the normal phase dispatch (preflight gates, worktree, environment, finalize) — the skip module does the full job in one sanctioned call.

Detect the skip flag before normal phase dispatch (argument order is irrelevant).
When `--skip-polish` is present, route directly to the internal skip handler's
polish path. When `--skip-refine` is present, route to its refine path. This is
advance-skill plumbing, not an agent-facing product command; the operator surface
is `/yoke advance PREFIX-N --skip-polish` or `/yoke advance PREFIX-N
--skip-refine`.

The skip module validates the current status against the pinned skill
binding, derives its hops from that definition's ordered stages and declared
transitions, emits both the canonical `ItemStatusChanged` events (with
`source=skip-polish` / `source=skip-refine`) and a sibling `SkipHopPerformed`
event, rebuilds the board after the final hop, and handles the claim lifecycle
(`handoff-to-usher` for `--skip-polish`, `finalize-exit` for `--skip-refine`).

**Do not combine `--skip-polish` / `--skip-refine` with an explicit target status, `--env`, `--no-worktree`, or `--force`.** Each skip flag owns the target — combining with a different target silently drops the other argument. Pass them alone.

## 1. Parse and Lookup

Keep the operator's token as the public item ref. Do not treat the numeric
tail of `PREFIX-N` as `items.id`. Function-call targets carry `public_ref` so
the dispatcher resolves the internal id (see [`workflow-context.md`](workflow-context.md)).

Read and follow [`workflow-context.md`](workflow-context.md). It resolves the
exact pin and exports `_status`, `_pinned_definition_json`,
`_generated_children`, `_worktree_policy`, and `_current_skill`. Do not continue
unless the read succeeds.

`implementation` is not an advance target, and neither is the transition out of
an `implement` binding's entry stage (for an issue, `refined-idea ->
implementing`). When either arrives, stop: implementation entry, the
implementation loop, and the review loop belong to the `implement` stage skill
bound across them, which calls this sub-skill only for its later status writes.

The calling skill stamped the session mode; this sub-skill does not restamp it.

The legacy `/tmp/yoke-current-item` marker file was retired when marker-based attribution was replaced with DB-backed lookups on the session's current-item field (see your `harness_sessions` packet stanza). Do **not** write that file.

Resolve the canonical target **inline** so the claim gate can run before any phase-doc reads. This is a local computation — Step 2 still owns the full forward-transition validation and re-entry semantics — but the target bucket (claim-holding vs. not) must be decided here so the claim fires before preflight:

```bash
# Resolve target locally so the claim gate below can run before phase-doc reads.
# Full validation happens in Step 2; this is just the minimum computation needed
# to decide claim vs. no-claim.
_arg="$1" # advance target argument (may be empty for auto-advance)
if [ -n "$_arg" ]; then
 _target="$_arg"
else
 _prog=$(printf '%s' "$_pinned_definition_json" | python3 -c 'import json,sys
envelope=json.load(sys.stdin)
print(" ".join(stage["id"] for stage in envelope["result"]["definition"]["stages"]))')
 _target=$(printf '%s\n' $_prog | awk -v cur="$_status" 'found==1{print; exit} $0==cur{found=1}')
fi

_target_skill=$(printf '%s' "$_pinned_definition_json" | python3 -c '
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
' "$_target")
```

For claim-holding targets (`reviewing-implementation`, `polishing-implementation`), call `claims.work.acquire` so the handler establishes the work claim and sets DB-backed active-item attribution in one transaction; for the calling skill's own claim it is an idempotent same-session re-claim:

```json
{
  "function": "claims.work.acquire",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "item", "public_ref": "PREFIX-N"},
  "intent": "advance_run",
  "payload": {"target": {"kind": "item", "public_ref": "PREFIX-N"}, "reason": "advance_run"}
}
```

For non-claim-holding targets (`reviewed-implementation`, `implemented`, `release`, `done`, or any planning-phase target), do not call the claim handler — the existing claim from the prior implementing/reviewing/polishing phase is released by finalize's early-handoff step.

**Claim semantics:**
- `claims.work.acquire` is idempotent for same-session re-claim — if the operator re-runs after a preflight failure, the response carries `result.already_owned=true` with `success=true`. No explicit release-on-failure is needed.
- An active work claim remains held across idle sweeps, process exit, and restart. A conflicting claimant must wait for explicit release, item completion or cancellation, or authorized session termination; heartbeat age does not transfer ownership. An already ended session with an inconsistent active claim can still be repaired by the reclaim path.
- If the item is actively held by another live session, the response carries `error.code="claim_conflict"` with the holder session id — stop advance and surface the error.
- Stop and SessionEnd hooks never release active claims. At an explicit handoff, run `yoke claims work release --all-mine`; the hooks close only an already claim-free session whose checkpoint has no remaining chain budget.

## 2. Determine Target Status

`$_target` was already resolved inline in Step 1 so the claim gate could run
before phase-doc reads. This step delegates forward-transition validation to
the shared lifecycle transition surface; the skill does not carry a second
stage table.

Then determine the target:

- **Explicit target = current status:** nothing to write.
 - If target is `reviewed-implementation` → reviewed-implementation re-entry. Delegate to the reviewed-implementation boundary message in [`finalize.md`](finalize.md) (`## Pre-Release Next-Step Guidance`) and **stop**. Do not advertise `/yoke polish` from inside the advance flow — the routed loop owns the polish handoff.
 - Otherwise → return to the calling skill's loop without a write; re-entering a lane belongs to the skill bound at the live stage.
- **Explicit target after current in the applicable progression:** Valid forward transition → continue to step 4.
- **Explicit target before current:** → stop (not valid).
- **No target (auto-advance):** Next status in the applicable progression. If already `done` → stop.

**Advance-skill transition semantics:**
- `implementing -> reviewing-implementation` — Enter the review phase. Review-phase fixes and follow-up edits continue in the same worktree.
- `reviewing-implementation -> reviewed-implementation` — Review is complete. The branch is now queued for polish.
- `reviewed-implementation -> polishing-implementation` — Routed polish has started and now owns the finishing pass.
- `polishing-implementation -> implemented` — Set by routed polish on success. Advance can also set this directly.

Next: [`phase-dispatch.md`](phase-dispatch.md).
