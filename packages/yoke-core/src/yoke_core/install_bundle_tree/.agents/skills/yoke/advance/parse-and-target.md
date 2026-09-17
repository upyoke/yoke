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

When the requested advance target is `implementation`, map it to the canonical status `implementing` for lifecycle comparisons. `implementation` is the advance-target name (the sub-skill path); `implementing` is the DB status. Keep using `implementation` as the advance target in operator-facing examples and routed `/yoke do` invocations.

**Immediately** stamp the session mode. For implementation entry (`_target = implementing`), defer the first work-claim acquisition to the orchestrator: its client-side write-guard identity probe must pass before `worktree_preflight.run_preflight` creates the claim or lane. For reviewing/polishing re-entry, acquire the claim below before phase-doc reads. The mode update keeps the board's active-session row showing `advance` instead of the default `wait`; claim acquisition establishes DB-backed active-item attribution.

Session-mode stamping is an internal advance-router action (`session-touch`
service-client handler; no registered product CLI wrapper). Do not teach or run a
module-shaped recipe for it in normal product flow. The item attribution itself is
established by the registered claim surface below.

The legacy `/tmp/yoke-current-item` marker file was retired when marker-based attribution was replaced with DB-backed lookups on the session's current-item field (see your `harness_sessions` packet stanza). Do **not** write that file.

Resolve the canonical target **inline** so the claim gate can run before any phase-doc reads. This is a local computation — Step 2 still owns the full forward-transition validation and re-entry semantics — but the target bucket (claim-holding vs. not) must be decided here so the claim fires before preflight:

```bash
# Resolve target locally so the claim gate below can run before phase-doc reads.
# Full validation happens in Step 2; this is just the minimum computation needed
# to decide claim vs. no-claim.
_arg="$1" # advance target argument (may be empty for auto-advance)
if [ "$_arg" = "implementation" ]; then
 _target="implementing"
elif [ -n "$_arg" ]; then
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

For re-entry claim-holding targets (`reviewing-implementation`, `polishing-implementation`), call `claims.work.acquire` so the handler establishes the work claim and sets DB-backed active-item attribution in one transaction. For `implementing`, skip this call; the implementation-entry orchestrator probes identity first, then `worktree_preflight.run_preflight` acquires the claim:

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
- Stale claims held by other sessions auto-reclaim after the configured stale-heartbeat window (`session_stale_ttl_minutes` in machine config; sessions with active holdings use `session_stale_ttl_with_holdings_minutes`) of heartbeat silence with no events emitted from the owning session in that window, or when the owning session has ended. `WorkReclaimed` is emitted in that case. Threshold owner: the harness session-claim implementation; resolver: `yoke_core.domain.sessions_analytics_core.DEFAULT_STALE_THRESHOLD_MINUTES` / `DEFAULT_STALE_WITH_HOLDINGS_THRESHOLD_MINUTES`.
- If the item is actively held by another live session, the response carries `error.code="claim_conflict"` with the holder session id — stop advance and surface the error.
- Stop and SessionEnd hooks never release active claims. At an explicit handoff, run `yoke claims work release --all-mine`; the hooks close only an already claim-free session whose checkpoint has no remaining chain budget.

## 2. Determine Target Status

`$_target` was already resolved inline in Step 1 so the claim gate could run
before phase-doc reads. This step delegates forward-transition validation to
the shared lifecycle transition surface; the skill does not carry a second
stage table.

Then determine the target:

- **Explicit target = current status:** Re-entry request.
 - If target resolves to `implementing` → read and follow **worktree re-entry** (step 3 below), then continue the pinned skill's implementation loop. Do **not** stop after surfacing the worktree path.
 - If target is `reviewing-implementation` → re-entry into review phase. Use **worktree re-entry** (step 3) to recover the worktree, then continue the review loop in that worktree. Do **not** ask the operator whether to review now.
 - If target is `reviewed-implementation` → reviewed-implementation re-entry. Delegate to the reviewed-implementation boundary message in [`finalize.md`](finalize.md) (`## Pre-Release Next-Step Guidance`) and **stop**. Do not advertise `/yoke polish` from inside the advance flow — the routed loop owns the polish handoff.
 - Otherwise → `Cannot advance PREFIX-N from '{current}' to '{target}' — not a valid forward transition.`
- **Advance target is `implementation` while current status is `reviewing-implementation`:** Treat this as an **implementation re-entry**. Do NOT mutate status backward; read and follow **worktree re-entry** (step 3 below), then continue the same implementation/review loop until review passes or a real blocker is hit. This preserves the single-worktree review-loop behavior for review-phase fixes rather than introducing a separate manual checkpoint.
- **Explicit target after current in the applicable progression:** Valid forward transition → continue to step 4.
- **Explicit target before current:** → stop (not valid), except for the `reviewing-implementation` → `implementation` re-entry above.
- **No target (auto-advance):** Next status in the applicable progression. If already `done` → stop.

**Advance-skill transition semantics:**
- `refined-idea -> implementing` — Implementation entry. Creates worktree and begins implementation.
- `implementing -> reviewing-implementation` — Enter the review phase. Review-phase fixes and follow-up edits continue in the same worktree.
- `reviewing-implementation` + advance target `implementation` — **Re-entry only.** This resumes the existing worktree without mutating status backward. The DB status stays `reviewing-implementation`.
- `reviewing-implementation -> reviewed-implementation` — Review is complete. The branch is now queued for polish.
- `reviewed-implementation -> polishing-implementation` — Routed polish has started and now owns the finishing pass.
- `polishing-implementation -> implemented` — Set by routed polish on success. Advance can also set this directly.

Next: [`reentry.md`](reentry.md) for a re-entry target, otherwise
[`phase-dispatch.md`](phase-dispatch.md).
