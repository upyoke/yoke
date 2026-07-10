# Usher — Merge Execution

Step 7: Execute merges for each item in dependency-safe order. Skip if `--deploy-only`.

**Error/rollback:** If a merge fails mid-batch, halt with clear state. The operator should be able to see exactly which items merged and which didn't. Never leave items in an ambiguous state between `implemented` and `done`.

**Context variables** (set by prior phases): merge-ordered items list, `_DEPLOY_ONLY`

If `_DEPLOY_ONLY`, skip entirely to deploy phase.

---

<!--
 BRANCH CLEANUP ORDERING CONTRACT
 1. Step 7c: Pre-merge ephemeral verification (before merge, gates it)
 2. Step 7d: `watch_merge merge-worktree` merges branch into main
 3. Step 8: `watch_merge done-transition --skip-deploy` runs cleanup
 DO NOT reorder these steps.
-->

## For each item in merge order:

### 7a. Re-verify status

```bash
yoke items get YOK-{N} status
```

- `done` → skip (idempotent)
- `release` → skip merge, proceed to deploy phase (already merged)
- Not `implemented` → skip with warning

### 7a2. Re-verify blocking verification QA

Before usher advances an item into `release`, confirm that all blocking
verification-phase requirements are already satisfied or waived:

```bash
_unsatisfied_verify=$(python3 -m yoke_core.cli.db_router query \
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
`browser_smoke`, `browser_diff`, or `e2e` verification requirements by itself.

### 7b. Advance to release

Call `lifecycle.transition.execute` from `implemented` to `release`. The handler runs the implemented → release gate and emits `ItemStatusChanged`.

```json
{
  "function": "lifecycle.transition.execute",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "item", "item_id": {N}},
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
 # Skip if conduct/polish already satisfied the ephemeral QA gate
 _already_passed_eph=$(python3 -m yoke_core.cli.db_router query \
 "SELECT COUNT(*) FROM qa_runs qr JOIN qa_requirements qreq ON qr.qa_requirement_id = qreq.id WHERE qreq.item_id = {N} AND qreq.qa_kind IN ('browser_smoke', 'browser_diff') AND qreq.qa_phase = 'verification' AND qr.verdict = 'pass'" 2>/dev/null) || _already_passed_eph="0"

 if [ -n "$_already_passed_eph" ] && [ "$_already_passed_eph" -gt 0 ]; then
 echo " Skipping pre-merge ephemeral-verify: already satisfied before usher"
 _pre_merge_verified=1
 else
 # Resolve and run ephemeral verify executor
 _item_project=$(yoke items get {N} project 2>/dev/null) || true
 _ev_github_repo=$(yoke projects github-binding status \
 --project "$_item_project" --field github_repo 2>/dev/null) || true
 # For epics, iterate all lanes; for issues, the resolver returns one branch.
 _ev_branches=$(python3 -m yoke_core.domain.worktree_item_resolve YOK-{N} --branches 2>/dev/null) || true
 if [ -z "$_ev_branches" ]; then
 echo "BLOCK: no worktree branch resolved for YOK-{N}"
 exit 1
 fi
 _ev_failed=0
 while IFS= read -r _ev_branch; do
 [ -n "$_ev_branch" ] || continue
 # ... resolve _ev_workflow, _ev_domain, _ev_head_sha for $_ev_branch ...
 python3 -m yoke_core.tools.executors ephemeral-verify "$_ev_github_repo" "$_ev_branch" "$_ev_workflow" "$_ev_domain" "$_ev_head_sha"
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

**Epic items delegate to `/yoke merge {N}` — never call `merge_worktree` directly for epics**:
```bash
_item_type=$(yoke items get {N} type)
if [ "$_item_type" = "epic" ]; then
 # Epics may have multiple worktree lanes; /yoke merge handles all lanes in
 # dependency-safe order, runs per-branch merge_worktree, and does bookkeeping.
 # Do NOT call merge_worktree directly on the epic ref — it only covers one lane.
 /yoke merge {N}
 # /yoke merge sets exit code; treat non-zero as merge failure for this item.
else
 # Issue-merge boundary call. YOKE_DONE_TRANSITION is the engine-owned
 # standalone-branch contract documented by runtime/api/engines/merge_worktree_prepare.py;
 # `done_transition` sets the same env var internally when it dispatches to
 # merge_worktree. Setting it here on the issue-merge boundary is the
 # documented call shape, not an ad-hoc bypass. The companion `# lint:no-guard-check`
 # is recorded as audit evidence so reviewers can grep the call site.
 YOKE_DONE_TRANSITION=1 python3 -m yoke_core.tools.watch_merge merge-worktree -- YOK-{N} # lint:no-guard-check
fi
```

**Engine contract:** `YOKE_DONE_TRANSITION=1` is the standalone-branch boundary the merge engine recognises (see `runtime/api/engines/merge_worktree_prepare.py` lines 141-147 for the guard, `runtime/api/engines/done_transition_merge_ops.py` line 124 for the internal-engine setter). The watcher call above invokes the same engine contract on the issue boundary because issue items have no done-transition intermediary.

**Streaming-wrapper form:** A merge is a long command, so per the Command Output streaming rule it normally runs under the watcher wrapper. `watch_merge merge-worktree` maps to `yoke_core.engines.merge_worktree`, but the wrapper **inherits the parent environment and does NOT auto-set or propagate `YOKE_DONE_TRANSITION=1`** — set it explicitly in the env prefix of the wrapper invocation too: `YOKE_DONE_TRANSITION=1 python3 -m yoke_core.tools.watch_merge merge-worktree -- YOK-{N}`. (`python3 -m yoke_core.tools.watch_merge --print-streaming-pair merge-worktree -- YOK-{N}` prints the background + Monitor pair; prepend `YOKE_DONE_TRANSITION=1` to the printed background command.)

**IMPROVISATION GUARD:** If lint blocks despite the audit comment, **STOP**. NEVER substitute raw done-transition or any other entrypoint for the issue-merge call.

### 7e. Handle merge result

**Scope:** This section applies to **issue items only**. Epic items use `/yoke merge {N}` (step 7d) which owns its own exit-code contract and merge loop — its failure mode is a non-zero exit from the `/yoke merge` invocation; revert to `implemented` and halt on any non-zero.

The merge watcher preserves the merge engine's small set of documented exit codes. Aligned this list with the real engine contract: any **unknown non-zero exit** is treated as a hard failure and the item is rolled back to `implemented` — never left stranded in `release`. Exit 6 is the one **recoverable** non-zero outcome: a retryable merge-lock coordination condition that must NOT roll the item back.

- **Exit 0:** `[release] YOK-{N} -- merge complete`. Proceed to the deploy phase.
- **Exit 3:** Parse `CONFLICT|file|classification` lines from stderr. For each conflicting file, inspect the conflict in the worktree and resolve using judgement (the classification is one input — additive conflicts are safe to union-merge, overlapping conflicts need codebase understanding). After resolving, `git add` and `git commit`, then re-run the merge command. If resolution is not confident, halt and report to operator.
- **Exit 1 (HALT — `usher-halt-merge-failure`):** Merge path failure — push, PR create, CI, PR merge, freshness re-check, or post-merge verification. Revert to `implemented`, release the work claim with `usher-halt-merge-failure`, then halt the batch and surface the engine's stderr block to the operator. Future/planned item ownership or a planned path claim is not a waiver for the current merge failure. Do not use `path-claim-override` for a planned future claim when dependency or claim reconciliation can resolve the ordering; override is last resort for irreducible live collisions and requires explicit operator approval. The merge engine prints an actionable `Error: merge phase '<phase>' failed` line and a `MergePullRequest*Failed` / `MergeTargetStale` / `MergeVerificationFailed` event is in the events ledger.
- **Exit 4 (HALT — `usher-halt-merge-failure`):** Worktree has user-authored dirty files at risk. Revert to `implemented`, release the work claim with `usher-halt-merge-failure`, then halt the batch and instruct the operator to resolve the dirty state before retry. The engine has already stashed the files; recover via `git -C {repo} stash list` / `git stash apply`.
- **Exit 5 (HALT — `usher-halt-merge-failure`, merge landed, cleanup failed):** The git/PR merge **already committed** on `{target}`, but post-merge view regeneration or board rebuild failed. This is a cleanup-class failure, NOT a merge failure. **Do NOT roll the item back to `implemented`** — the branch is already merged and deleted upstream, and pretending otherwise will desync status from git. Instead:
 1. **Leave the item in `release`** (do not mutate status).
 2. Release the work claim with `usher-halt-merge-failure` so a fresh `/yoke usher YOK-{N}` can re-acquire it.
 3. Halt the entire usher batch — do NOT proceed to later items.
 4. Surface the engine's stderr block (it prints `Error: post-merge view regeneration failed ...` plus a `Recovery:` line).
 5. Query the events ledger for the precise `MergeEngineFailed` row: `yoke events query --event-name MergeEngineFailed --item {N}`. The envelope carries `phase=post_merge_cleanup` and `merge_committed=true`, distinguishing this class from an ordinary merge failure.
 6. Instruct the operator to fix the view-regen / board-rebuild issue and resume with `/yoke usher YOK-{N}`. On resume, step 7a re-verifies status — because the item is still `release`, usher will skip merge and proceed straight to deploy.
- **Exit 6 (RECOVERABLE — retryable merge-lock contention):** The merge engine's pre-acquire `merge_lock.check()` reported a holding lock and the bounded retry budget was exhausted before the row was pruned. This is a **coordination outcome**, NOT a halt-class merge failure — the merge itself never began. The engine prints the final lock message plus a `Recovery: retryable merge-lock condition (pre-acquire retry budget exhausted)` line that names the branch. Handling:
 1. **Leave the item in `release`** (do not mutate status). Do NOT issue the `usher_rollback_to_implemented` lifecycle transition for this exit code.
 2. Release the work claim with `handoff-to-usher` (NOT `usher-halt-merge-failure` / `usher-halt-unexpected`) so a fresh `/yoke usher YOK-{N}` can re-acquire it cleanly.
 3. Halt the current usher batch — do NOT proceed to later items.
 4. Tell the operator / `/yoke do` loop to rerun `/yoke usher YOK-{N}` once the holding lock clears (PID death, TTL expiry, or a subsequent `merge_lock.check()` call pruning the orphan row).
- **Any other non-zero exit (HALT — `usher-halt-unexpected`):** Treat as unknown failure. Revert to `implemented` with the same rollback/release/report sequence as exit 1, but release the work claim with `usher-halt-unexpected`. DO NOT leave the item in `release`. DO NOT substitute raw done-transition to paper over the failure. Emit the unknown exit code in the halt message so operators can file a bug. **Exit 6 is excluded from this branch** — see the dedicated recoverable bullet above.

**Halt-class release contract:** For every halt branch above (exits 1, 4, 5, and any unknown non-zero — NOT exit 6), the work-claim release with the matching halt-class reason MUST run BEFORE the halt summary / recovery prose is printed. The `release_reason_intent` audit value is the structured halt-class string (`usher-halt-merge-failure` for exits 1, 4, 5; `usher-halt-unexpected` for unknown non-zero exits). Downstream tooling (doctor, Ouroboros) reads this value. The four halt classes are terminal release intents per `yoke_core.domain.release_intent_classification.TERMINAL_RELEASE_INTENTS`. Do NOT use `completed` for a halt path — `completed` is reserved for successful finalize paths. **Exit 6's release intent is `handoff-to-usher`** (also a terminal release intent in the same module), used because the merge attempt did not begin and the next `/yoke usher YOK-{N}` invocation should re-acquire cleanly.

**Rollback + halt-class release sequence (exits 1, 4, and any unknown non-zero — NOT exit 5):** revert `release → implemented` first, then release the claim with the halt-class reason. Exit 5 skips the rollback step but still performs the halt-class release.

Rollback step (exits 1, 4, unknown non-zero only):

```json
{
  "function": "lifecycle.transition.execute",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "item", "item_id": {N}},
  "intent": "usher_rollback_to_implemented",
  "payload": {"source_status": "release", "target_status": "implemented", "rollback_reason": "<merge_worktree exit code>"}
}
```

Halt-class release step (all four halt branches — operator/debug adapter; dispatches `claims.work.release`):

```bash
# <halt-class> is usher-halt-merge-failure for exits 1, 4, 5;
# usher-halt-unexpected for any other non-zero exit.
yoke claims work release --item YOK-{N} --reason <halt-class>
```

If the release call itself fails, the halt summary MUST say the release failed and include the failure class / holder when available; do not print a clean recovery summary while the claim is still live.

Then halt the entire usher batch — do NOT proceed to later items in the merge-ordered list. Emit a clear halt summary including:
- the offending item ID,
- the engine exit code,
- the halt-class reason that was released (or the release failure if release did not succeed),
- the last `Merge*Failed` / `MergeTargetStale` / `MergeVerificationFailed` event (query `events` for `event_name LIKE 'Merge%Failed' OR event_name = 'MergeTargetStale'`),
- instructions to resume with `/yoke usher YOK-{N}` after the underlying cause is fixed.

**Never** ignore the exit code and continue. **Never** mutate status to `done` or beyond without a fresh successful `python3 -m yoke_core.tools.watch_merge merge-worktree` run.

### 7f. Post-Merge CI Check (ADVISORY)

After all merges complete, check main CI:
```bash
_repo=$(yoke projects github-binding status --project "$_usher_project" \
 --field github_repo)
yoke github-actions check-ci "$_repo" ci.yml --branch main \
 --project "$_usher_project"
```

The command resolves the project's verified App binding and uses a short-lived
installation token; no host `gh` binary is needed. `state == "failed"` →
advisory warning. `passed` / `running` / `no_runs` → skip silently.
GitHub Actions `queued` collapses into `running` for the deploy-stage poller.

---

After merges, return to router for deploy phase.
