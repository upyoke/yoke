# Usher — Merge Execution

Step 7: Execute merges for each item in dependency-safe order. Skip if `--deploy-only`.

**Error/rollback:** If a merge fails mid-batch, halt with clear state. The operator should be able to see exactly which items merged and which didn't. Never leave items in an ambiguous state between `implemented` and `done`.

**Context variables** (set by prior phases): merge-ordered items list, `_DEPLOY_ONLY`

If `_DEPLOY_ONLY`, skip entirely to deploy phase.

---

<!--
 BRANCH CLEANUP ORDERING CONTRACT
 1. Step 7c: Pre-merge ephemeral verification (before merge, gates it)
 2. Step 7d: `watch_merge merge-worktree` merges the branch into the project's registered default branch
 3. Step 8: `watch_merge done-transition --skip-deploy` runs cleanup
 DO NOT reorder these steps.
-->

## For each item in merge order:

### 7a. Re-verify status

```bash
yoke items get PREFIX-{N} status
```

- `done` → skip (idempotent)
- `release` → skip merge, proceed to deploy phase (already merged)
- Not `implemented` → skip with warning

Resolve the item's immutable workflow pin once for the merge decision. Use the
logical version returned by `workflows.item.get` to read the exact definition;
never substitute the registry's current version:

```bash
_usher_pin_json=$(yoke workflows item get PREFIX-{N} --json) || exit 1
_usher_workflow_id=$(printf '%s' "$_usher_pin_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["workflow_id"])')
_usher_workflow_version=$(printf '%s' "$_usher_pin_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["workflow_version"])')
_usher_status=$(printf '%s' "$_usher_pin_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["status"])')
_usher_definition_json=$(yoke workflows version get \
 "$_usher_workflow_id" "$_usher_workflow_version" --json) || exit 1
_usher_generated_children=$(printf '%s' "$_usher_definition_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["definition"]["policies"]["generated_children"])')
_usher_worktree_policy=$(printf '%s' "$_usher_definition_json" | python3 -c \
 'import json,sys; print(json.load(sys.stdin)["result"]["definition"]["policies"]["worktrees"])')
_usher_current_skill=$(printf '%s' "$_usher_definition_json" | python3 -c '
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
' "$_usher_status")
[ "$_usher_current_skill" = "usher" ] || {
 echo "BLOCK: pinned skill $_usher_current_skill owns stage $_usher_status, not usher"
 exit 1
}
```

The interpreter uses the runtime's half-open interval
(`from_stage_id <= current < through_stage_id`) and halts unless the current
stage resolves to skill `usher`.

### 7a2. Re-verify blocking verification QA

Before usher advances an item into `release`, confirm that all blocking
verification-phase requirements are already satisfied or waived:

```bash
_unsatisfied_verify=$(yoke db read --format lines \
 "SELECT COUNT(*) FROM qa_requirements qr \
 WHERE qr.item_id = {N} AND qr.qa_phase = 'verification' \
 AND qr.blocking_mode = 'blocking' AND qr.waived_at IS NULL \
 AND NOT EXISTS (SELECT 1 FROM qa_runs qrun \
 WHERE qrun.qa_requirement_id = qr.id \
 AND qrun.verdict = 'pass')" 2>/dev/null) || _unsatisfied_verify="0"
```

If `_unsatisfied_verify` is non-zero, **HALT**. Do **not** advance to
`release`, do **not** merge, and do **not** treat `ephemeral-verify` as a
substitute for this gate.

`ephemeral-verify` only proves the preview deployment workflow completed and a
preview URL was surfaced. It does **not** satisfy unsatisfied item-level
Browser method cases or `e2e` verification requirements by itself.

### 7b. Advance to release

Call `lifecycle.transition.execute` from `implemented` to `release`. The handler runs the implemented → release gate and emits `ItemStatusChanged`.

```json
{
  "function": "lifecycle.transition.execute",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "item", "item_ref": "PREFIX-{N}"},
  "intent": "usher_enter_release",
  "payload": {"source_status": "implemented", "target_status": "release"}
}
```

### 7c. Pre-merge ephemeral verification

Check if flow has `ephemeral-verify` stage:
```bash
_item_flow=$(yoke items get {N} deployment_flow 2>/dev/null) || true
_pre_merge_verified=0
_eph_next_stage=""

if [ -n "$_item_flow" ] && [ "$_item_flow" != "null" ]; then
 _stages_json=$(yoke deployment-flows stages "$_item_flow" 2>/dev/null) || true
 _has_eph_verify=$(printf '%s' "$_stages_json" | grep -c '"ephemeral-verify"') || true

 if [ "$_has_eph_verify" -gt 0 ]; then
 # Skip if conduct/polish already satisfied a Browser method case.
 _already_passed_eph=$(yoke db read --format lines \
 "SELECT COUNT(*) FROM qa_runs qr \
 JOIN qa_requirements qreq ON qr.qa_requirement_id = qreq.id \
 WHERE qreq.item_id = {N} \
 AND qreq.qa_phase = 'verification' \
 AND qreq.method_id IN ('browser-check', 'browser-inspection') \
 AND qr.verdict = 'pass'" 2>/dev/null) || _already_passed_eph="0"

 if [ -n "$_already_passed_eph" ] && [ "$_already_passed_eph" -gt 0 ]; then
 echo " Skipping pre-merge ephemeral-verify: already satisfied before usher"
 _pre_merge_verified=1
 else
 # Resolve and run the ephemeral verify step runner
 _item_project=$(yoke items get {N} project 2>/dev/null) || true
 _ev_github_repo=$(yoke projects github-binding status \
 --project "$_item_project" --field github_repo 2>/dev/null) || true
 # The resolver returns every lane allowed by the pinned worktree policy.
 _ev_branches=$(python3 -m yoke_core.domain.worktree_item_resolve PREFIX-{N} --branches 2>/dev/null) || true
 if [ -z "$_ev_branches" ]; then
 echo "BLOCK: no worktree branch resolved for PREFIX-{N}"
 exit 1
 fi
 _ev_failed=0
 while IFS= read -r _ev_branch; do
 [ -n "$_ev_branch" ] || continue
 # ... resolve _ev_workflow, _ev_domain, _ev_head_sha for $_ev_branch ...
 python3 -m yoke_core.tools.step_runners ephemeral-verify "$_ev_github_repo" "$_ev_branch" "$_ev_workflow" "$_ev_domain" "$_ev_head_sha"
 _ev_rc=$?
 if [ "$_ev_rc" -ne 0 ]; then
 echo "BLOCK: ephemeral-verify failed for branch $_ev_branch (exit $_ev_rc)"
 _ev_failed="$_ev_rc"
 break
 fi
 done <<EOF
$_ev_branches
EOF
 if [ "$_ev_failed" -ne 0 ]; then
 exit "$_ev_failed"
 fi
 fi
 _pre_merge_verified=1
 # Find next stage after ephemeral-verify for pipeline resume
 _eph_next_stage=$(printf '%s' "$_stages_json" | python3 -c "
import sys, json
stages = json.load(sys.stdin)
names = [s['name'] for s in stages]
try:
 idx = names.index('ephemeral-verify')
 if idx + 1 < len(names):
 print(names[idx + 1])
except (ValueError, IndexError):
 pass
" 2>/dev/null) || true
 fi
fi
```

**On failure:** revert from `release` back to `implemented` via `lifecycle.transition.execute` with `payload.rollback_reason="ephemeral_verify_failed"`, then halt the batch.

Track `_pre_merge_verified` and `_eph_next_stage` for deploy phase.

### 7d. Execute merge

Select the merge engine from the pinned child/lane policies:

```bash
if [ "$_usher_generated_children" = "epic_tasks" ] \
 && [ "$_usher_worktree_policy" = "worker_and_integration_lanes" ]; then
 # Generated tasks across worker lanes may leave multiple lanes to merge.
 # /yoke merge handles every lane in dependency-safe order and owns the
 # parent-item bookkeeping.
 # Do not call merge-worktree directly on the parent ref; that covers one lane.
 /yoke merge {N}
elif [ "$_usher_generated_children" = "none" ] \
 && [ "$_usher_worktree_policy" = "single_implementation_lane" ]; then
 # Single-lane merge boundary call. `merge-item` is the standalone-item merge
 # operation: it takes the merge lock, lands the branch on the project base
 # branch, stamps merged_at, and publishes. `--skip-status` leaves the
 # lifecycle status to the deploy phase below, which owns it here.
 yoke watch merge merge-item -- PREFIX-{N} --skip-status
else
 echo "BLOCK: unsupported pinned merge policy: children=$_usher_generated_children worktrees=$_usher_worktree_policy"
 exit 1
fi
```

**Engine contract:** an item branch with no epic lane is a standalone merge, and every standalone merge routes through one operation — `yoke merge item`, wrapped here as `watch_merge merge-item`. The operation declares the standalone permission to the merge engine as an argument, so the engine's refusal for an unpermitted standalone branch stays intact for every other caller. Contract and portability constraints: [`docs/archive/decisions/standalone-item-merge.md`](../../../../docs/archive/decisions/standalone-item-merge.md).

A preflight refusal whose only issues are missing or stale commit-bound verdicts is recovered inside `yoke merge item`: it re-records hand acceptance runs (or re-runs SHA-bound Command cases) against the lane head and then lands. That class is not a halt, and it must not roll the item back to `implemented` or release the claim. A later non-recoverable merge failure still follows the exit-code halt rules below.

**Streaming-wrapper form:** A merge is a long command, so per the Command Output streaming rule it runs under the watcher wrapper. `yoke watch merge --print-streaming-pair merge-item -- PREFIX-{N} --skip-status` prints the background + Monitor pair.

**IMPROVISATION GUARD:** If lint blocks despite the audit comment, **STOP**. NEVER substitute raw done-transition or any other entrypoint for the single-lane merge call.

### 7e. Handle merge result

**Scope:** This section applies only to
`worktrees=single_implementation_lane`. The task-graph policy uses `/yoke merge
{N}` (step 7d), which owns its exit-code contract and lane loop; treat any
non-zero exit from that invocation as merge failure, revert to `implemented`,
and halt.

The merge watcher preserves the merge engine's small set of documented exit codes. Aligned this list with the real engine contract: any **unknown non-zero exit** is treated as a hard failure and the item is rolled back to `implemented` — never left stranded in `release`. Exit 6 is the one **recoverable** non-zero outcome: a retryable merge-lock coordination condition that must NOT roll the item back.

- **Exit 0:** `[release] PREFIX-{N} -- merge complete`. Proceed to the deploy phase.
- **Exit 3:** Parse `CONFLICT|file|classification` lines from stderr. For each conflicting file, inspect the conflict in the worktree and resolve using judgement (the classification is one input — an additive classification already means the union was computed and found valid for the file's format, while overlapping conflicts need codebase understanding). After resolving, `git add` and `git commit`, then re-run the merge command. If resolution is not confident, halt and report to operator.
- **Exit 1 (HALT — `usher-halt-merge-failure`):** Merge path failure — push, PR create, CI, PR merge, freshness re-check, or post-merge verification. Revert to `implemented`, release the work claim with `usher-halt-merge-failure`, then halt the batch and surface the engine's stderr block to the operator. Future/planned item ownership or a planned path claim is not a waiver for the current merge failure. Do not use `path-claim-override` for a planned future claim when dependency or claim reconciliation can resolve the ordering; override is last resort for irreducible live collisions and requires explicit operator approval. The merge engine prints an actionable `Error: merge phase '<phase>' failed` line and a `MergePullRequest*Failed` / `MergeTargetStale` / `MergeVerificationFailed` event is in the events ledger.
- **Exit 4 (HALT — `usher-halt-merge-failure`):** Worktree has user-authored dirty files at risk. Revert to `implemented`, release the work claim with `usher-halt-merge-failure`, then halt the batch and instruct the operator to resolve the dirty state before retry. The engine has already stashed the files; recover via `git -C {repo} stash list` / `git stash apply`.
- **Exit 5 (HALT — `usher-halt-merge-failure`, merge landed, cleanup failed):** The git/PR merge **already committed** on `{target}`, but post-merge view regeneration or board rebuild failed. This is a cleanup-class failure, NOT a merge failure. **Do NOT roll the item back to `implemented`** — the branch is already merged and deleted upstream, and pretending otherwise will desync status from git. Instead:
 1. **Leave the item in `release`** (do not mutate status).
 2. Release the work claim with `usher-halt-merge-failure` so a fresh `/yoke usher PREFIX-{N}` can re-acquire it.
 3. Halt the entire usher batch — do NOT proceed to later items.
 4. Surface the engine's stderr block (it prints `Error: post-merge view regeneration failed ...` plus a `Recovery:` line).
 5. Query the events ledger for the precise `MergeEngineFailed` row: `yoke events query --event-name MergeEngineFailed --item {N}`. The envelope carries `phase=post_merge_cleanup` and `merge_committed=true`, distinguishing this class from an ordinary merge failure.
 6. Instruct the operator to fix the view-regen / board-rebuild issue and resume with `/yoke usher PREFIX-{N}`. On resume, step 7a re-verifies status — because the item is still `release`, usher will skip merge and proceed straight to deploy.
- **Exit 6 (RECOVERABLE — retryable merge-lock contention):** The merge engine's pre-acquire `merge_lock.check()` reported a holding lock and the bounded retry budget was exhausted before the row was pruned. This is a **coordination outcome**, NOT a halt-class merge failure — the merge itself never began. The engine prints the final lock message plus a `Recovery: retryable merge-lock condition (pre-acquire retry budget exhausted)` line that names the branch. Handling:
 1. **Leave the item in `release`** (do not mutate status). Do NOT issue the `usher_rollback_to_implemented` lifecycle transition for this exit code.
 2. Release the work claim with `handoff-to-usher` (NOT `usher-halt-merge-failure` / `usher-halt-unexpected`) so a fresh `/yoke usher PREFIX-{N}` can re-acquire it cleanly.
 3. Halt the current usher batch — do NOT proceed to later items.
 4. Tell the operator / `/yoke do` loop to rerun `/yoke usher PREFIX-{N}` once the holding lock clears (PID death, TTL expiry, or a subsequent `merge_lock.check()` call pruning the orphan row).
- **Any other non-zero exit (HALT — `usher-halt-unexpected`):** Treat as unknown failure. Revert to `implemented` with the same rollback/release/report sequence as exit 1, but release the work claim with `usher-halt-unexpected`. DO NOT leave the item in `release`. DO NOT substitute raw done-transition to paper over the failure. Emit the unknown exit code in the halt message so operators can file a bug. **Exit 6 is excluded from this branch** — see the dedicated recoverable bullet above.

**Halt-class release contract:** For every halt branch above (exits 1, 4, 5, and any unknown non-zero — NOT exit 6), the work-claim release with the matching halt-class reason MUST run BEFORE the halt summary / recovery prose is printed. The `release_reason_intent` audit value is the structured halt-class string (`usher-halt-merge-failure` for exits 1, 4, 5; `usher-halt-unexpected` for unknown non-zero exits). Downstream tooling (doctor, Ouroboros) reads this value. The four halt classes are terminal release intents per `yoke_core.domain.release_intent_classification.TERMINAL_RELEASE_INTENTS`. Do NOT use `completed` for a halt path — `completed` is reserved for successful finalize paths. **Exit 6's release intent is `handoff-to-usher`** (also a terminal release intent in the same module), used because the merge attempt did not begin and the next `/yoke usher PREFIX-{N}` invocation should re-acquire cleanly.

**Rollback + halt-class release sequence (exits 1, 4, and any unknown non-zero — NOT exit 5):** revert `release → implemented` first, then release the claim with the halt-class reason. Exit 5 skips the rollback step but still performs the halt-class release.

Rollback step (exits 1, 4, unknown non-zero only):

```json
{
  "function": "lifecycle.transition.execute",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "item", "item_ref": "PREFIX-{N}"},
  "intent": "usher_rollback_to_implemented",
  "payload": {"source_status": "release", "target_status": "implemented", "rollback_reason": "<merge_worktree exit code>"}
}
```

Halt-class release step (all four halt branches — operator/debug adapter; dispatches `claims.work.release`):

```bash
# <halt-class> is usher-halt-merge-failure for exits 1, 4, 5;
# usher-halt-unexpected for any other non-zero exit.
yoke claims work release --item PREFIX-{N} --reason "<halt-class>"
```

If the release call itself fails, the halt summary MUST say the release failed and include the failure class / holder when available; do not print a clean recovery summary while the claim is still live.

Then halt the entire usher batch — do NOT proceed to later items in the merge-ordered list. Emit a clear halt summary including:
- the offending item ID,
- the engine exit code,
- the halt-class reason that was released (or the release failure if release did not succeed),
- the last `Merge*Failed` / `MergeTargetStale` / `MergeVerificationFailed` event (query `events` for `event_name LIKE 'Merge%Failed' OR event_name = 'MergeTargetStale'`),
- instructions to resume with `/yoke usher PREFIX-{N}` after the underlying cause is fixed.

**Never** ignore the exit code and continue. **Never** mutate status to `done` or beyond without a fresh successful `yoke watch merge merge-worktree` run.

### 7f. Post-Merge CI Check (ADVISORY)

After all merges complete, repeat the same project-policy resolution from Step
4b: `github_repo` from `projects.github_binding.status`, `workflow_file` from
the `ci_workflow_file` capability, and `default_branch` from `projects.get`.
When all values exist, run:

```bash
yoke github-actions check-ci "{repo}" "{workflow_file}" \
 --branch "{default_branch}" --project "{project}"
```

The command resolves the project's verified App binding and uses a short-lived
installation token; no host `gh` binary is needed. `state == "failed"` →
advisory warning. `passed` / `running` / `no_runs` → skip silently.
GitHub Actions `queued` collapses into `running` for the deploy-stage poller.

---

After merges, return to router for deploy phase.
