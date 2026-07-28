---
name: advance
description: "Advance a backlog item to the next status in its lifecycle, or to a specific target status."
argument-hint: "{YOK-N} [status]"
---

# Sub-skill called by conduct, usher, do/loop, and routed dispatch.
# The `implementation` form (`/yoke advance YOK-N implementation`) is also
# operator-facing for workflows whose pinned definition binds `advance` across
# implementation entry. Other advance targets remain internal-only.

# /yoke advance {YOK-N} [status]

Advance a backlog item's status forward through its pinned workflow. The shared
lifecycle interpreter validates every transition from the item's immutable
workflow version; this skill coordinates the surrounding operator journey.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Arguments

- `{YOK-N}` — Backlog item ID. Accepts prefixed IDs, zero-padded prefixed IDs, or bare numeric IDs.
- `[status]` — Optional target status or advance-target name. If omitted, advances to the next status in the lifecycle. The advance target `implementation` is end-to-end **in the same harness session**: worktree creation is a pure filesystem + DB operation (not a session boundary), the work-claim acquired in preflight is the session's authority over the new worktree, and the same session continues into the implementation sub-skill ([implementing/implementation.md](implementing/implementation.md)) and the review loop until `reviewed-implementation`. No parent-session stop, no claim release on worktree entry, no manual relaunch from the worktree. Stopping at `implementing` and announcing `/yoke polish` (or any later step) as "next" remains the hand-off-to-operator anti-pattern this contract exists to prevent.
- `--env <name>` — Optional. Update the item's `deployed_to` field. Valid environments are resolved per-project from DB tables (`environments` via `sites`, `deployment_flows.target_env`, `project_capabilities`). Can be combined with a status advance or used standalone on an already-done item.
- `--no-worktree` — Optional. Skip worktree creation when advancing to `implementing`. The item will remain on the current branch with no isolation. Use this for evidence-only / validation / proof items that intentionally make no repo changes; the done-transition empty-branch guard only applies when a worktree branch exists.
- `--force` — Optional. Override the file-level collision blocker, generated-task existence/completion gates, or merge verification gate.
- `--skip-polish` — Optional. Operator-asserted fast path across the pinned `polish` executor segment. Dispatches through the advance skill's internal skip handler (`yoke_core.domain.advance_skip`; no registered product CLI wrapper), derives the hops from the binding's `from_stage_id`, `through_stage_id`, ordered stages, and transitions, emits a `SkipHopPerformed` event, and releases the item claim with reason `handoff-to-usher`. Requires the current status to equal that pinned binding's entry stage. Use when the mission deliberately skips the polish phase (for example theme-swap missions from [.yoke/strategy/PROMPTS.md](../../../../.yoke/strategy/PROMPTS.md) that declare `SKIP: refine and polish phases`). Do NOT pass a target status with this flag — the flag owns the target.
- `--skip-refine` — Optional. Operator-asserted fast path across a pinned `refine` executor segment's gate-free bookkeeping rungs. The internal skip handler (`yoke_core.domain.advance_skip`; no registered product CLI wrapper) validates the current stage against its allowlist and advances to that binding's handoff. It emits a `SkipHopPerformed` event. Use when refine deliberation is unnecessary (low-risk content swaps, copy edits). Do NOT pass a target status with this flag.

Both skip flags:
- Are operator-discoverable via `/yoke advance --help` and via `/yoke do` routing when the mission declares a skip.
- Emit an `ItemStatusChanged` event with `source=skip-polish` or `source=skip-refine` (honest telemetry for Ouroboros).
- Use distinct `YOKE_CLAIM_BYPASS` reasons (`skip-polish`, `skip-refine`) so the pre-implementation safety invariant (claim-bypass only for gate-free bookkeeping rungs) stays intact.
- Refuse invalid current statuses with a clear error. The bypass is operator-asserted, not auto-inferred.

Example invocations:

```bash
# Theme-swap mission declares "SKIP: polish":
/yoke advance YOK-N --skip-polish

# Low-risk copy edit declares "SKIP: refine":
/yoke advance YOK-N --skip-refine
```

### Evidence-Only Items

Items that require no code changes (validation, proof, guidance updates) should use `--no-worktree` when advancing to `implementing`. This leaves the item without an active implementation lane in `item_worktrees`, so the done-transition engine (`packages/yoke-core/src/yoke_core/engines/done_transition.py`) skips the empty-branch guard (exit 8).

**If an evidence-only item was advanced WITHOUT `--no-worktree`** and later hits exit 8 during done-transition or usher, the recovery path is:
1. Complete the caller's rollback to `implemented`; lane release is refused at every other status.
2. Ensure this session holds the item claim: `yoke claims work acquire --item YOK-{N} --reason evidence-only-recovery`.
3. Read the registered implementation-lane path and prove it has no modified tracked, untracked, or ignored files:

```bash
_wt_path=$(yoke item-worktrees get YOK-{N} \
 --lane-role implementation --field path)
if [ -z "$_wt_path" ] || [ "$_wt_path" = "null" ] || [ ! -d "$_wt_path" ]; then
 echo "Blocked: the registered worktree path cannot be verified."
 exit 1
fi
_wt_dirty=$(git -C "$_wt_path" status --porcelain \
 --ignored=matching --untracked-files=all)
_wt_git_rc=$?
if [ "$_wt_git_rc" -ne 0 ] || [ -n "$_wt_dirty" ]; then
 echo "Blocked: preserve or commit every worktree file before lane release."
 exit 1
fi
```

4. Immediately release the attested lane: `yoke item-worktrees release YOK-{N} --all-active --reason evidence-only-recovery`. The adapter repeats the branch and cleanliness checks, and the server requires the item to remain `implemented` with exactly one active implementation lane matching the attestation.
5. Re-run the done-transition or usher command.

The empty-branch guard exists to catch accidental merges of branches with no work. For items that intentionally have no code changes, the guard is a false positive — releasing the active lane records is the canonical recovery.

## Philosophy

**Events at every transition.** Status transitions are significant system moments. When investigating transition failures, query the events table: `yoke events query --item {N}`. The events table captures `ItemStatusChanged` events with full context.

**Verify before claiming done (P-9).** The done-transition must confirm every AC is addressed, not just the core implementation. Execution-type deliverables (running a script, configuring secrets) need explicit verification separate from code correctness (P-52).

## Lifecycle authority

The item's `workflow_id` and `workflow_version_id` select the immutable
definition. Never reconstruct a progression in this skill. Read the served
definition for navigation and let `lifecycle.transition.execute` enforce the
pinned version, stage order, gates, and registered executor binding.

## Steps

### 0. Skip-Flag Fast Path

**Run this check before Step 1.** When `--skip-polish` or `--skip-refine` is present in the argument list, the advance skill hands control directly to the canonical skip module and skips the normal phase dispatch (preflight gates, worktree, environment, finalize) — the skip module does the full job in one sanctioned call.

Detect the skip flag before normal phase dispatch (argument order is irrelevant).
When `--skip-polish` is present, route directly to the internal skip handler's
polish path. When `--skip-refine` is present, route to its refine path. This is
advance-skill plumbing, not an agent-facing product command; the operator surface
is `/yoke advance YOK-{N} --skip-polish` or `/yoke advance YOK-{N}
--skip-refine`.

The skip module validates the current status against the pinned executor
binding, derives its hops from that definition's ordered stages and declared
transitions, emits both the canonical `ItemStatusChanged` events (with
`source=skip-polish` / `source=skip-refine`) and a sibling `SkipHopPerformed`
event, rebuilds the board after the final hop, and handles the claim lifecycle
(`handoff-to-usher` for `--skip-polish`, `finalize-exit` for `--skip-refine`).

**Do not combine `--skip-polish` / `--skip-refine` with an explicit target status, `--env`, `--no-worktree`, or `--force`.** Each skip flag owns the target — combining with a different target silently drops the other argument. Pass them alone.

### 1. Parse and Lookup

Extract the numeric part from the argument (strip `YOK-` prefix, leading zeros).

Read and follow [`workflow-context.md`](workflow-context.md). It resolves the
exact pin and exports `_status`, `_pinned_definition_json`,
`_generated_children`, `_worktree_policy`, `_parallelism_policy`, and
`_current_executor`. Do not continue unless the read succeeds.

When the requested advance target is `implementation`, map it to the canonical status `implementing` for lifecycle comparisons. `implementation` is the advance-target name (the sub-skill path); `implementing` is the DB status. Keep using `implementation` as the advance target in operator-facing examples and routed `/yoke do` invocations.

**Immediately** stamp the session mode and register the work claim so this session owns the item before any phase-doc reads, worktree setup, or preflight gates run. The mode update keeps the board's active-session row showing `advance` instead of the default `wait`; the claim is what sets the active item attribution — `cmd_claim` internally calls `_set_current_item` on the session row, so this single call both acquires the exclusive work claim and establishes the DB-backed current-item signal used by the board, scheduler, and observe-tool hook.

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

_target_executor=$(printf '%s' "$_pinned_definition_json" | python3 -c '
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
' "$_target")
```

For claim-holding targets (`implementing`, `reviewing-implementation`, `polishing-implementation`), call `claims.work.acquire` so the handler establishes the work claim and sets the DB-backed active-item attribution in one transaction:

```json
{
  "function": "claims.work.acquire",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "item", "item_id": {N}},
  "intent": "advance_run",
  "payload": {"target": {"kind": "item", "item_id": {N}}, "reason": "advance_run"}
}
```

For non-claim-holding targets (`reviewed-implementation`, `implemented`, `release`, `done`, or any planning-phase target), do not call the claim handler — the existing claim from the prior implementing/reviewing/polishing phase is released by finalize's early-handoff step.

**Claim semantics:**
- `claims.work.acquire` is idempotent for same-session re-claim — if the operator re-runs after a preflight failure, the response carries `result.already_owned=true` with `success=true`. No explicit release-on-failure is needed.
- Stale claims held by other sessions auto-reclaim after the configured stale-heartbeat window (`session_stale_ttl_minutes` in machine config; per-executor overrides via `session_stale_ttl_minutes_<executor>_override`, e.g. `session_stale_ttl_minutes_codex_override`) of heartbeat silence with no events emitted from the owning session in that window, or when the owning session has ended. `WorkReclaimed` is emitted in that case. Threshold owner: `runtime/harness/harness_sessions.py` (`cmd_claim` stale-window query); resolver: `yoke_core.domain.sessions_analytics_core.DEFAULT_STALE_THRESHOLD_MINUTES` / `EXECUTOR_STALE_TTL_OVERRIDES_MINUTES`.
- If the item is actively held by another live session, the response carries `error.code="claim_conflict"` with the holder session id — stop advance and surface the error.
- Stop and SessionEnd hooks never release active claims. At an explicit handoff, run `yoke claims work release --all-mine`; the hooks close only an already claim-free session whose checkpoint has no remaining chain budget.

### 2. Determine Target Status

`$_target` was already resolved inline in Step 1 so the claim gate could run
before phase-doc reads. This step delegates forward-transition validation to
the shared lifecycle transition surface; the skill does not carry a second
stage table.

Then determine the target:

- **Explicit target = current status:** Re-entry request.
 - If target resolves to `implementing` → read and follow **worktree re-entry** (step 3 below), then continue the pinned executor's implementation loop. Do **not** stop after surfacing the worktree path.
 - If target is `reviewing-implementation` → re-entry into review phase. Use **worktree re-entry** (step 3) to recover the worktree, then continue the review loop in that worktree. Do **not** ask the operator whether to review now.
 - If target is `reviewed-implementation` → reviewed-implementation re-entry. Delegate to the reviewed-implementation boundary message in [`finalize.md`](finalize.md) (`## Pre-Release Next-Step Guidance`) and **stop**. Do not advertise `/yoke polish` from inside the advance flow — the routed loop owns the polish handoff.
 - Otherwise → `Cannot advance YOK-{N} from '{current}' to '{target}' — not a valid forward transition.`
- **Advance target is `implementation` while current status is `reviewing-implementation`:** Treat this as an **implementation re-entry**. Do NOT mutate status backward; read and follow **worktree re-entry** (step 3 below), then continue the same implementation/review loop until review passes or a real blocker is hit. This preserves the single-worktree review-loop behavior for review-phase fixes rather than introducing a separate manual checkpoint.
- **Explicit target after current in the applicable progression:** Valid forward transition → continue to step 4.
- **Explicit target before current:** → stop (not valid), except for the `reviewing-implementation` → `implementation` re-entry above.
- **No target (auto-advance):** Next status in the applicable progression. If already `done` → stop.

**Advance-executor transition semantics:**
- `refined-idea -> implementing` — Implementation entry. Creates worktree and begins implementation.
- `implementing -> reviewing-implementation` — Enter the review phase. Review-phase fixes and follow-up edits continue in the same worktree.
- `reviewing-implementation` + advance target `implementation` — **Re-entry only.** This resumes the existing worktree without mutating status backward. The DB status stays `reviewing-implementation`.
- `reviewing-implementation -> reviewed-implementation` — Review is complete. The branch is now queued for polish.
- `reviewed-implementation -> polishing-implementation` — Routed polish has started and now owns the finishing pass.
- `polishing-implementation -> implemented` — Set by routed polish on success. Advance can also set this directly.

### 3. Worktree Re-entry

When the advance target triggers re-entry into the current worktree:
- current = `implementing`, advance target = `implementation` (or `implementing`)
- current = `reviewing-implementation`, advance target = `reviewing-implementation`
- current = `reviewing-implementation`, advance target = `implementation` (re-entry)

Locates the existing worktree, prepares `WORKTREE_PATH`, and resumes the implementation/review loop. Do **not** stop after surfacing the path.

```bash
_item_project=$(yoke items get {N} project 2>/dev/null)
if [ -n "$_item_project" ] && [ "$_item_project" != "null" ] && [ "$_item_project" != "" ]; then
 _wt_repo=$(yoke projects get --project "$_item_project" --field repo_path)
else
 _wt_repo=$(git rev-parse --show-toplevel)
fi

if [ "$_worktree_policy" = "single_implementation_lane" ]; then
 _wt_branch=$(yoke item-worktrees get YOK-{N} \
  --lane-role implementation --field branch 2>/dev/null)
elif [ "$_worktree_policy" = "worker_and_integration_lanes" ] \
 || [ "$_worktree_policy" = "worker_lanes_optional_integration" ]; then
 if [ "$_current_executor" = "conduct" ]; then
  echo "CONTRACT ERROR: the pinned conduct executor owns YOK-{N}'s task lanes."
  echo "Use /yoke conduct YOK-{N} to re-enter or advance a generated task lane."
 else
  echo "CONTRACT ERROR: executor $_current_executor owns a multi-lane policy that advance cannot select."
 fi
 exit 1
else
 echo "CONTRACT ERROR: unsupported pinned worktree policy $_worktree_policy."
 exit 1
fi
```

- If `_wt_branch` set → check `$_wt_repo/.worktrees/$_wt_branch`.
 - Directory exists → set `WORKTREE_PATH` to the absolute path and continue.
 - Missing → recreate through the source-dev/admin worktree helper, update DB, set `WORKTREE_PATH`, and continue. No registered product CLI wrapper exists for direct worktree creation; normal operators use `/yoke advance YOK-{N} implementation`.
- If `_wt_branch` empty → create new worktree, update DB, set `WORKTREE_PATH`, and continue.

After `WORKTREE_PATH` is ready:
- If current status is `implementing`, continue with step 4 as the normal single-lane implementation loop selected by the pinned `advance` binding.
- If current status is `reviewing-implementation`, resume the review loop in the same worktree immediately:
 1. Review the current branch against the spec and acceptance criteria.
 2. Make any follow-up fixes in that same worktree.
 3. Re-run the relevant verification and refresh QA evidence.
 4. When review actually passes, immediately run `/yoke advance YOK-{N} reviewed-implementation`.
 **Commit invariant:** The advance to `reviewed-implementation` must not leave the worktree dirty. Finalize step 9 handles this automatically — when `WORKTREE_PATH` is set, it stages worktree changes (`git -C "$WORKTREE_PATH" add -A`) before checking the index. Review-loop fixes, including newly created files, are committed as part of the advance, not left behind.
- Never stop with "Want me to review now?" or a numbered handoff menu unless a real blocker prevents continued work.

### 4. Phase Dispatch

**Implementation entry (`_target = "implementing"`) is orchestrator-driven.** When `_target` resolves to `implementing` (the `/yoke advance YOK-N implementation` path), invoke the canonical orchestrator instead of reading and executing each phase doc inline:

Before invocation, require `_target_executor=advance` and
`_worktree_policy=single_implementation_lane`. Route `conduct` to `/yoke
conduct YOK-{N}` and halt on every other mismatch; this engine is an
executor-specific contract, not a generic transition shortcut.

The skill-router internal entrypoint is the advance implementation-entry engine
for `YOK-{N}`. This engine is not a product CLI wrapper; the operator surface is
still `/yoke advance YOK-{N} implementation`.

Pass `--no-worktree` for evidence-only items, `--force` for the operator-asserted override path, `--qa-bypass` to bypass implementation QA when truly needed. The orchestrator composes preflight gates → `worktree_preflight.run_preflight` (bundles claim + activation + worktree creation/reuse) → environment (capability-gated) → finalize (`lifecycle.transition.execute`) inside one Python process and emits one `AdvancePhaseCompleted` event per phase. It is idempotent: rerunning against an item already at `implementing` reuses the worktree, re-acquires the same claim, and skips the status flip rather than re-emitting it. On preflight failure the orchestrator stops before activation/worktree/finalize and prints the gate narrative; on `worktree-create-failed` it releases the claim with reason `worktree-create-failed`; on finalize failure the worktree and claim remain in place so the next invocation can converge. Verify the phase trail with `yoke events query --item {N} --event-name AdvancePhaseCompleted`.

After the orchestrator returns success, the same harness session continues into worktree-bound implementation work via the implementing sub-skill handoff documented in [`finalize.md`](finalize.md) (`## Implementation-entry Sub-skill Handoff`).

The phase reference docs ([`preflight.md`](preflight.md), [`activation.md`](activation.md), [`worktree.md`](worktree.md), [`environment.md`](environment.md), [`finalize.md`](finalize.md)) remain in the tree as reference material the orchestrator consumes through its Python code — they document the contract each composed helper honors, not a per-call agent-driven sequencing recipe.

**Non-implementing targets** (manual advance to `reviewing-implementation`, `reviewed-implementation`, `polishing-implementation`, `implemented`, `release`, `done`, or any planning-phase target) still run through the legacy phase docs below. The orchestrator only covers implementation entry today; the post-implementation phases retain their existing doc-driven flow.

**Preflight Gates:** Read `.agents/skills/yoke/advance/preflight.md`
- Applies to: all non-implementing transitions (hard-block dependency, AC,
  coverage, pinned-executor handoff, generated-task, merge-verification, and
  done-redirect gates).
- Generated-task gates run only when
  `policies.generated_children=epic_tasks`; executor-specific gates run only
  when the target path crosses that pinned binding. Merge and done gates remain
  target-stage-specific.

**Browser QA:** Read `.agents/skills/yoke/advance/browser-qa.md`
- Applies to: target = `reviewed-implementation`, `implemented`, or `polishing-implementation`
- Skip for all other targets

**Deployed-stack QA:** Read `.agents/skills/yoke/advance/project-e2e.md`
- Applies to: workflow transition = `release`
- Materializes attached QA plans and executes every `Command` case whose project-owned configuration declares the migrated `e2e` scope, with `BASE_URL` supplied from the ephemeral environment
- Self-skips when no deployed-stack plan is attached; skip for all other transitions

**Finalize:** Read `.agents/skills/yoke/advance/finalize.md`
- Applies to: all non-implementing transitions that reach this point
- Handles: status update, GitHub sync, commit, report, implementation-complete next-step guidance, implementing sub-skill handoff (implementing-target callers reach the sub-skill handoff via the orchestrator's success exit; this doc still documents the handoff contract for both paths)

## Query Ordering and Parallel-Safe Groups

Respect the ordering constraints below. Only reads explicitly described as
independent may run in parallel.

**Step 1 — Pinned workflow lookup:**
- Call `workflows.item.get` first. Its `workflow_id` and logical
  `workflow_version` select the exact `workflows.version.get` read used for
  auto-advance navigation; never substitute the current workflow definition.
- After `workflows.item.get` returns, the pinned `workflows.version.get` read
  and `items get {N} title` are independent and may run in parallel.

**Preflight — Reconciliation gate:**
- `items get {N} deployment_flow`, `items get {N} project`, `items get {N} github_issue` — all independent reads

**Preflight — Dependency + AC gates:**
- `evaluate-gate "YOK-{N}" "activation"` and `check_ac_presence "YOK-{N}"` — independent gate evaluations

**Environment — Ephemeral setup:**
- `yoke ephemeral-env update "$_env_id" url "$_ephemeral_url"` and `yoke ephemeral-env update "$_env_id" deployed_sha "$_deployed_sha"` — independent writes to the same env record (different fields)

**Implementation — Edit batching:**
- When multiple Edit calls target different files, run them in parallel. Use `replace_all: true` when the old string is unique enough for a safe global replace.
