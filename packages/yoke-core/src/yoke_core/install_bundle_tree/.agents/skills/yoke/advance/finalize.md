# Advance — Finalize

> **Orchestrator role:** For implementation-entry advances, the orchestrator [`packages/yoke-core/src/yoke_core/engines/advance_implementation_entry.py`](../../../../packages/yoke-core/src/yoke_core/engines/advance_implementation_entry.py) dispatches `lifecycle.transition.execute` directly (the "Update Status" step below) and emits the outcome as `AdvancePhaseCompleted{phase="finalize"}`. The GitHub sync, commit, claim-handoff, and next-step-guidance prose below remains the canonical contract for those operator-facing steps — the orchestrator's reference for what the dispatch handler triggers downstream. The implementing sub-skill handoff (`## Implementation-entry Sub-skill Handoff`) still runs after the orchestrator returns success.

Called by the advance router after all gates and phase-specific work complete. Updates status, syncs GitHub, commits, and reports.

**Context variables** (set by router): `{N}`, `{NNN}` (zero-padded), `_title`, `_status` (old), `_target` (new), `--env` value, `WORKTREE_PATH` (absolute path to item worktree, set by worktree phase or re-entry; empty/unset when advancing on main or with `--no-worktree`)

---

## Implementation-entry requires a refined source (step 5f)

Implementation-entry advance expects the item exactly one rung before `implementing` — `refined-idea` (issue) or `planned` (epic) — and the orchestrator dispatches that single `lifecycle.transition.execute` (the "Update Status" step below). The advance router does **not** walk intermediate pre-implementation rungs: an item still at `idea` / `refining-idea` (or an epic mid-planning) is not advanced straight to `implementing` in one call.

To move a pre-refine item toward implementation, reach a refined source first, then advance:

- Run `/yoke refine` — the normal path; it authors the spec/plan and lands `refined-idea` / `planned`.
- Or pass `--skip-refine` to fast-forward the gate-free bookkeeping rungs when refine deliberation is unnecessary (see below).

Never hand-write intermediate `items scalar update --field status` hops to climb toward `implementing`: raw status writes are claim-protected and rejected with `ClaimVerificationDenied`. The sanctioned bookkeeping fast-forward is `--skip-refine`.

### Skip-flag bookkeeping hops

`yoke_core.domain.advance_skip` owns the operator-asserted skip-phase hops. `PRE_IMPLEMENTATION_STATUSES` (in `yoke_core.domain.lifecycle_progression`) marks the gate-free bookkeeping rungs; each skip allowlist stays disjoint from any rung that carries a real gate, so claim-bypass is only ever granted for bookkeeping moves.

The operator-facing `--skip-polish` and `--skip-refine` flags (documented in `SKILL.md` step 0) dispatch to `advance_skip` and return before reaching this finalize step — they handle the full lifecycle themselves (hops, events, claim release):

- `--skip-polish` → `advance_skip.skip_polish`: `reviewed-implementation` → `polishing-implementation` → `implemented` with `YOKE_CLAIM_BYPASS=skip-polish`. Claim releases with reason `handoff-to-usher`.
- `--skip-refine` → `advance_skip.skip_refine`: `idea`/`refining-idea` → `refined-idea` or `plan-drafted`/`refining-plan` → `planned` (epic) with `YOKE_CLAIM_BYPASS=skip-refine`. Claim releases opportunistically with reason `finalize-exit`.

Both emit a `SkipHopPerformed` event alongside the canonical `ItemStatusChanged` events. Ouroboros distinguishes skipped hops via the `via` field (`skip-polish` or `skip-refine`) and the `skipped_phase` field on the event envelope. The distinct bypass reasons keep the pre-implementation safety invariant intact: claim-bypass is granted only for the narrowly-allowlisted bookkeeping hops, never for a real gate transition.

## Update Status (step 6)

Call `lifecycle.transition.execute` — the handler runs the gate for `({_status} → {_target})`, posts the GitHub status-change comment, and emits `ItemStatusChanged`. The canonical request model is `LifecycleTransitionRequest` (payload fields: `target_status`, optional `source_status`, optional `reason`).

```json
{
  "function": "lifecycle.transition.execute",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "item", "item_id": {N}},
  "intent": "advance_finalize",
  "payload": {"target_status": "{_target}", "source_status": "{_status}", "reason": "advance_finalize"},
  "options": {"sync_github_body": true}
}
```

## Early Claim Handoff (step 6b)

Release or hand off the execution-owned work claim **immediately after the
status write**, before GitHub sync, commit, summary, or next-step guidance.
This guarantees that an interruption between "status updated" and "summary
emitted" cannot orphan a claim — even if the session dies mid-finalize, the
scheduler will see the claim as released.

Claim lifecycle by target status:
- `implementing`, `reviewing-implementation`, `polishing-implementation` — the
 session is **still actively working** on this item; hold the claim. Do NOT
 release.
- `reviewed-implementation` — review phase is complete, next stop is polish
 (fresh command entrypoint); release with reason `handoff-to-polish`.
- `implemented` — implementation chain is complete, next stop is usher
 (fresh command entrypoint); release with reason `handoff-to-usher`.
- Any other terminal-for-this-session target — release with reason
 `finalize-exit`.

Compute `_release_intent` from the target:

- `implementing`, `reviewing-implementation`, `polishing-implementation` — session keeps the claim; do not call release.
- `reviewed-implementation` → `handoff-to-polish`
- `implemented` → `handoff-to-usher`
- any other target → `finalize-exit`

For every target that resolves to a non-empty release intent, call `claims.work.release`:
Operator/debug adapter: `yoke claims work release --item YOK-{N} --reason "<_release_intent>"`.

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim_id>},
  "intent": "advance_finalize",
  "payload": {"claim_id": <claim_id>, "reason": "<_release_intent>"}
}
```

**Failure handling.** The response envelope distinguishes failure modes via `error.code` (`not_owned`, `already_terminal`, `item_not_found`, `domain_error`). Each failure also emits an `ItemClaimReleaseFailed` event (severity WARN) carrying the holder session when applicable. The advance does **not** fail when release fails — the status transition has already committed in step 6 and forcing the advance to fail after that point would corrupt the operator mental model. The response warning is the operator's signal that something needs investigation; the events ledger has the full payload (`item_id`, `caller_session_id`, `holder_session_id`, `failure_reason`, `target_status`, `release_reason_intent`).

The `claims.work.release` handler delegates to `yoke_core.domain.sessions.release_work_claim_for_execution`, which releases the claim and clears session focus atomically. Generic attribution helpers (`set_current_item` / `clear_current_item`) are deliberately **not** used here — they stay attribution-only so that create/status mutation paths like `backlog._maybe_set_session_current_item` do not accidentally touch claim state.

## Update deployed_to (step 7, only if `--env` provided)

Call `items.scalar.update` for the `deployed_to` field. The handler validates the environment name against the project's `environments` table and rejects unknown values.

```json
{
  "function": "items.scalar.update",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "item", "item_id": {N}},
  "intent": "advance_deploy_env",
  "payload": {"field": "deployed_to", "value": "{env-name}"}
}
```

If the response carries `error.code="invalid_environment"`:
> Invalid environment: {env-name}. Valid environments: local, dev, staging, production

## GitHub Sync (step 8)

The status-change comment and body sync are downstream side effects of the `lifecycle.transition.execute` call in step 6 (request `options.sync_github_body=true`). The response envelope reports `warnings[].code="github_sync_degraded"` if the sync failed; the advance status transition still succeeded.

## Commit (step 9)

`.yoke/BOARD.md` is untracked — do NOT stage it. It is regenerated locally by board rebuilds for operator readability.

**WORKTREE_PATH resolution fallback:** If `WORKTREE_PATH` was not propagated from the worktree phase (agent context loss, re-entry via backward compat path), resolve it from the DB before committing. This prevents accidental main-branch commits when a worktree exists.

```bash
_finalize_item_type=$(yoke items get {N} type 2>/dev/null) || true
if [ -z "$WORKTREE_PATH" ] && [ "$_finalize_item_type" != "epic" ]; then
 _wt_branch=$(yoke items get {N} worktree 2>/dev/null)
 if [ -n "$_wt_branch" ] && [ "$_wt_branch" != "null" ]; then
 _item_project=$(yoke items get {N} project 2>/dev/null)
 if [ -n "$_item_project" ] && [ "$_item_project" != "null" ] && [ "$_item_project" != "" ]; then
 _wt_repo=$(yoke projects get --project "$_item_project" --field repo_path)
 else
 _wt_repo=$(git rev-parse --show-toplevel)
 fi
 _candidate="$_wt_repo/.worktrees/$_wt_branch"
 if [ -d "$_candidate" ]; then
 WORKTREE_PATH="$_candidate"
 fi
 fi
fi
```

**Worktree-scoped staging:** When `WORKTREE_PATH` is set (worktree-backed implementation or review loop), stage all worktree changes before checking the index. This ensures review-loop fixes made in the worktree, including newly created files, are committed as part of the advance — the agent must not leave a dirty worktree behind when exiting `reviewing-implementation`. The staging is explicitly worktree-scoped via `git -C "$WORKTREE_PATH"` to avoid accidentally staging unrelated repo-root files. Gitignored generated views are excluded by git's own ignore rules.

**Text-sensitive stale-string blocker:** Before the worktree-scoped commit for `reviewing-implementation` or `reviewed-implementation`, re-run the blocking stale-string audit in the commit block below. If it fails, stop without staging or committing.

**Worktree-required guard:** If the target is an implementation-phase status (`implementing`, `reviewing-implementation`, `reviewed-implementation`, `polishing-implementation`) and `WORKTREE_PATH` is still unset after the DB fallback, something went wrong upstream — the worktree phase should have created one. **Stop with an error** rather than silently committing on main.

```bash
_worktree_required_targets="implementing reviewing-implementation reviewed-implementation polishing-implementation"
if [ -z "$WORKTREE_PATH" ] && echo "$_worktree_required_targets" | grep -qw "{_target}"; then
 echo "ERROR: target is {_target} but no worktree found for YOK-{N}. The worktree phase should have created one. Aborting commit to prevent main-branch pollution."
 # Do NOT commit. Surface the error and stop.
else
 if [ -n "$WORKTREE_PATH" ] && [ -d "$WORKTREE_PATH" ]; then
 if echo "reviewing-implementation reviewed-implementation" | grep -qw "{_target}"; then
 python3 -m yoke_core.domain.stale_string_audit verify "YOK-{N}" "$WORKTREE_PATH" || {
 echo "ERROR: stale-string audit blocked the advance commit for YOK-{N}. Fix the remaining stale test strings (or add explicit quoted old strings to the spec/body so the gate can derive them), then re-run /yoke advance."
 exit 1
 }
 fi
 # Stage worktree changes without touching repo-root state
 git -C "$WORKTREE_PATH" add -A
 git -C "$WORKTREE_PATH" diff --cached --quiet || git -C "$WORKTREE_PATH" commit -m "YOK-{N}: {_status} → {_target}"
 else
 # Main-branch path (planning advances, --no-worktree, release/done bookkeeping):
 # commit only what is already staged. Do NOT run git add -A here —
 # that would sweep unrelated dirty files into a misleading transition commit.
 git diff --cached --quiet || git commit -m "YOK-{N}: {_status} → {_target}"
 fi
fi
```

**When `WORKTREE_PATH` is unset** (main-branch flows, `--no-worktree`, bookkeeping-only advances): the step falls through to the cached-only check, preserving the lightweight commit-what-was-already-staged behavior. **Never run `git add -A` on main** — the else branch intentionally stages nothing; only pre-staged files are committed.

### Snapshot sync after commit

After any commit produced by this finalize step (worktree-scoped or main-branch), the agent SHOULD sync the project's committed git tree snapshot for the new HEAD. The global `.git/hooks/post-commit` shim installed by `yoke project install` covers this in the happy case, but fresh clones where the operator has not yet run the install will not have the hook yet. Defense in depth:

```bash
yoke project snapshot sync "${WORKTREE_PATH:-.}" --hook
```

This is advisory — a snapshot miss does not block the advance. The next `path-claim-activate` or boundary check call will surface a clear error if it matters. Yoke-internal commit-emitting code paths (`packages/yoke-core/src/yoke_core/engines/done_transition.py` and `packages/yoke-core/src/yoke_core/engines/merge_worktree.py`) already invoke `ensure_snapshot_at` directly after their commit calls; this finalize step is the operator-skill mirror.

## Report (step 10)

> **YOK-{N}** ({_title}): `{_status}` → `{_target}`

Show lifecycle position with current status highlighted.

If no linked GitHub issue:
> Tip: GitHub issue creation is normally handled by `/yoke idea` and lifecycle
> sync side effects. If a manual sync is needed, use
> `yoke items github-sync YOK-{N}`; legacy DB-router GitHub-sync helpers are
> operator-debug only and are not normal product-flow recipes.

## Compact-Resistant Summary (step 10b)

After every advance, emit this structured block. It survives context compaction and prevents re-reading phase docs on subsequent advances in the same session.

```
## Advance Context — YOK-{N}

- **Item:** YOK-{N} — {_title}
- **Transition:** `{_status}` → `{_target}`
- **Worktree:** {WORKTREE_PATH or "none (main branch)"}
- **Project:** {_item_project}
- **Test command:** {_cmd_full or "uv run --frozen python3 -m yoke_core.tools.watch_pytest -- runtime/api/ runtime/harness/ tests/" (yoke default)}
- **Advance to reviewed-implementation:** `/yoke advance YOK-{N} reviewed-implementation`
- **Phase docs already loaded:** preflight, worktree, environment, finalize, implementing
- **Do-loop context (if inside /yoke do):** step {step}/{MAX_CHAIN_STEPS}, chainable={chainable}. Whether this advance is a completed handler depends on `{_target}` — do NOT treat every advance as a finished chain step.
  - When `{_target}` is `implementing` or `reviewing-implementation`: the advance contract is NOT complete. Stay in this same session and worktree, run the implementation/review/fix/verify loop, and proceed to `/yoke advance YOK-{N} reviewed-implementation` only when review actually passes. Returning to /yoke do Step C (chain decision) before that point treats `reviewing-implementation` as a completed handler when it isn't, and burns a chain step against the same item.
  - When `{_target}` is `reviewed-implementation` (real review boundary): the advance contract IS complete. The claim was already released in step 6b with `handoff-to-polish`. Return to /yoke do Step C (chain decision) so the chain checkpoint persists and the loop can decide whether to re-offer (typically for polish).
  - For any other target (planning hops, `implemented`, `release`, `done` bookkeeping): return to /yoke do Step C (chain decision) after this advance completes so the chain checkpoint persists and the loop can decide whether to re-offer.
```

Emit this block as regular output text (not a comment or hidden metadata). The block serves two purposes:
1. Re-anchors the agent after context compaction erases earlier phase-doc reads.
2. Provides the exact advance command for the next transition so the agent does not need to re-derive it.

## Pre-Release Next-Step Guidance

**If target was `implemented` (issue or epic items):** `implemented` is the pre-release success state — it means implementation complete, ready for release. The claim was already released in step 6b with reason `handoff-to-usher`. This is a command boundary: do **not** continue merge/deploy work by mutating later statuses in the same finalize flow. Emit:
 > **Next step:** Run `/yoke usher YOK-{N}` to merge and deploy.

If the operator explicitly wants usher next, start `/yoke usher YOK-{N}` as a fresh command entrypoint so usher can claim the item itself.

**If target was `reviewing-implementation` (issue items):** The item has entered the review phase. This is still implementation work in the same worktree, not a new manual-only checkpoint. Do **not** stop here during an autonomous `/yoke advance` or `/yoke do` run. Stay in the existing worktree, perform the review/fix/verify loop immediately, and when the branch is actually ready for `reviewed-implementation` run:
 > `/yoke advance YOK-{N} reviewed-implementation`

Only emit a blocking summary and stop if some real blocker prevents the review loop from continuing.

**If target was `reviewed-implementation` (issue or epic items):** Meaningful implementation review is complete. The claim was already released in step 6b with reason `handoff-to-polish`. This is a command boundary: stop the inner advance flow here and do **not** continue directly into polish from the same finalize pass; polish is a fresh command entrypoint that must claim the item itself. When the advance is running inside a routed `/yoke do` chain, return to the loop's chain decision step (`/yoke do` Step C) so the loop can re-offer (typically into polish). When the advance is invoked directly outside `/yoke do`, emit exactly one boundary message and stop the turn:
 > **Next step:** Return to `/yoke do` Step C (chain decision) so the routed loop can pick up the next step, or stop and leave the item ready for a fresh command entrypoint. Direct operator invocation of any command remains available outside the routed flow.

**Test pass is not gate satisfaction.** A green test suite means the implementation behaves as expected; the **reviewed-implementation gate** (run by the advance to `reviewed-implementation`) checks something different — that every blocking `qa_requirements` row for the item has a passing `qa_runs` entry recorded. Both must hold. If you have just finished implementation work and tests are passing, summarize that as "tests pass" — never "all gates pass" — until the routed `/yoke advance YOK-N reviewed-implementation` actually completes its phase dispatch (browser QA + project E2E + the reviewed-implementation gate) and updates status. To preview the gate verdict before transitioning, use the registered summary surface: `yoke qa gate-summary --item YOK-N --target reviewed-implementation` for a standalone issue, or `yoke qa gate-summary --epic-id <epic_id> --task-num <task_num> --target reviewed-implementation` for an epic task. Direct `items update ... status reviewed-implementation` is rejected by the gate even when tests are green.

**If target was `polishing-implementation` (issue or epic items):** Routed polish is actively in progress or has been resumed. The session keeps its claim. Emit:
 > **Next step:** Continue `/yoke polish YOK-{N}` until it advances to `implemented`.

## Implementation-entry Sub-skill Handoff

**If target was `implementing` (issue or epic items, with issue entry surfaced as `/yoke advance YOK-{N} implementation`):** Read and follow `.agents/skills/yoke/advance/implementing/SKILL.md`. Pass `{N}`, `{NNN}`, `{_title}`, `{WORKTREE_PATH}`. The current session holds the work-claim on YOK-{N} (acquired in preflight) and has provisioned the worktree — both newly created and re-entered worktrees are same-session, no relaunch. The sub-skill handles QA seeding + implementation kickoff for both workflow types. **Return after sub-skill completes.**
