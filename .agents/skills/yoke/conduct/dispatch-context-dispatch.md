# Dispatch Execution: Engineer/Tester Loop and Post-PASS Steps (5g–5p)

Extracted from `dispatch-context.md`. Covers Engineer dispatch orchestration (5g), main merge (5h), Tester dispatch reference (5i), post-PASS advancement (5o), and epic auto-chaining (5p).

---

## 5g. Parallel Engineer Dispatch

**Context-minimal output handling:** When Engineers return, extract only the success/failure indicator and the commit count from the Agent result summary. Read the submission receipt from `epic_progress_notes` via `submission-receipt-get`; do not parse the `---SUBMISSION-CHECKS-START---` block from Agent result text. Write reflections to DB immediately (step 5m). Do not retain the Engineer's full output text in context -- the work product lives in the worktree and the receipt lives in the DB.

Record the attempt baseline and dispatch the Engineer.

**Task fan-out variable contract:** In epic task fan-out, `N` / `_epic_id` remains the parent backlog item and each parallel member is an epic task from `_task_ids`. Before any per-task command below, hydrate the unsuffixed lane variables from the task's suffixed state:

```bash
_branch_var="_worktree_branch_${_task_id}"
_path_var="_worktree_path_${_task_id}"
_worktree_branch="${!_branch_var}"
_worktree_path="${!_path_var}"
```

Do not reuse a sibling task's `_worktree_path` or `_worktree_branch`; this is what preserves the per-task worktree lanes created by the Architect/refine flow.

**Record attempt and task baselines** (sequentially, before dispatch). The per-task `epic_task` work-claim is acquired later in `engineer-tester-dispatch.md` Step 3b, so the orchestrator does not yet hold authority over the lane worktree filesystem; read via the main checkout's branch ref instead (branches are repo-global, same SHA, `lint_session_cwd` authorizes `${MAIN_ROOT}` as control plane):
```bash
_branch_var="_worktree_branch_${_task_id}"
_worktree_branch="${!_branch_var}"
ATTEMPT_BASELINE_{_id}=$(git -C "${MAIN_ROOT}" rev-parse "${_worktree_branch}")
```
For epic items, also record the current progress-note count so post-return validation can verify a new note landed with any new commit:
```bash
# Epic items only:
_progress_note_count_before_{_id}=$(yoke db read --format lines "SELECT COUNT(*) FROM epic_progress_notes WHERE epic_id='${_epic_id}' AND task_num=${_task_id}" 2>/dev/null || echo 0)
```

**Record task baselines:** On first dispatch of each epic item, record the task baseline for scoped Tester diffs. This value is preserved across retries -- only set when `_attempt_{_id} = 1`. Same control-plane-via-branch-ref reasoning as the ATTEMPT_BASELINE read above (no per-task claim yet):
```bash
# On first attempt only (epic items):
if [ "${_attempt_{_id}}" = "1" ]; then
 TASK_BASELINE_{_id}=$(git -C "${MAIN_ROOT}" rev-parse "${_worktree_branch}")
fi
```
For issue items, `TASK_BASELINE` is not needed -- the full diff IS the per-task diff.

Initialize per-item attempt tracking:
```
_attempt_{_id}=1
_max_attempts={--max-attempts value, default 5}
_tester_output_failures_{_id}=0
```

**Branch-ahead detection:** Before dispatching the Engineer, check for pre-existing implementation commits on the worktree branch. Items with commits ahead of main (issues) or ahead of `TASK_BASELINE` (epics) on their first attempt skip Engineer dispatch and go directly to the Tester.

```bash
_has_implementation_{_id}=false
if [ "${_attempt_{_id}}" = "1" ]; then
 # Read from main checkout via branch ref — per-task claim not yet acquired.
 _merge_base=$(git -C "${MAIN_ROOT}" merge-base "${_worktree_branch}" main)
 _worktree_head=$(git -C "${MAIN_ROOT}" rev-parse "${_worktree_branch}")

 # Issues: compare merge-base with HEAD
 # Epics (first task): TASK_BASELINE == merge-base, so compare TASK_BASELINE with HEAD
 # Epics (subsequent tasks in chain): TASK_BASELINE != merge-base, always dispatch Engineer
 if [ "${_type}" = "issue" ]; then
 if [ "$_merge_base" != "$_worktree_head" ]; then
 _has_implementation_{_id}=true
 fi
 elif [ "${_type}" = "epic" ]; then
 # Only skip for first task on branch (TASK_BASELINE == merge-base)
 if [ "${TASK_BASELINE_{_id}}" = "$_merge_base" ] && [ "${TASK_BASELINE_{_id}}" != "$_worktree_head" ]; then
 _has_implementation_{_id}=true
 fi
 fi
fi
```

If `_has_implementation_{_id}` is true, skip the Engineer dispatch:
- Emit log line: `[SKIP] YOK-{N} task {_task_id}: implementation already on branch, skipping to Tester`
- **Seed task-level review requirement** (idempotent). `review_seed` now auto-advances epic tasks to `reviewing-implementation`:
 - **Epic only:** `yoke workflow-item epic-task review-seed --epic "$_epic_id" --task-num "$_task_id"`
 - **Issue:** invoke the Yoke advance skill for `YOK-${_id}` with target `reviewing-implementation`.
- Skip the post-Engineer commit sweep for this item.
- The item proceeds to the Tester dispatch (step 5i).

On retry attempts (`_attempt > 1`), `_has_implementation` is always false -- Engineer is always dispatched.

**Run 5f-rehydrate** for each task before dispatch (see [dispatch-context-rehydrate.md](dispatch-context-rehydrate.md)). Store the result as `_rehydration_block_{_id}`.

**Engineer prompt template:** See [dispatch-context-prompts.md](dispatch-context-prompts.md) for the full Engineer prompt template.

**Active path-claim coverage in the prompt.** The dispatch prompt MUST surface the Engineer's pre-authorized write budget so the Engineer can apply the proactive widen-before-write workflow without first running `path-claim-list` by hand. Pull the coverage from the live claim:

```bash
# Single-target source of truth for the Engineer's write budget. Lists
# the active claim's declared paths (declared_paths / declared_targets,
# joined through path_claim_targets -> path_targets.path_string); do
# NOT teach `path_claims.covered_paths` as a DB column.
_claim_coverage=$(yoke claims path list --item YOK-${_id} --state active)
```

Inline the resulting paths under a `## Active Path Claim Coverage` heading in the Engineer prompt. For epic tasks, follow this with a `## Planned (Widen Before Write)` block listing entries from the parent epic's `## File Budget` that are not yet in the active claim — these are the paths the Engineer must widen onto before the first write. The Engineer's canonical body teaches the workflow; surfacing the data here removes the recovery-crawl class of failure where the Engineer creates a new file and then spends N tool calls discovering it needs to widen.

The Tester's dispatch prompt MUST include the same `## Active Path Claim Coverage` block read-only (per the Tester no-write contract in `runtime/agents/tester.md` § *Path-Claim Awareness*) so the Tester knows which paths are in-scope for validation versus paths whose failures route back to the parent session as "uncovered fix path" findings.

**After ALL Engineers return** (the Agent tool blocks until each returns):

**AUTONOMOUS CONTINUATION REQUIRED:** The subagent has returned. IMMEDIATELY continue to the next step below. Do NOT stop, do NOT wait for user input, do NOT generate a conversational summary and pause. Emit a one-line checkpoint: `[CONTINUE] Engineer returned for YOK-{N}. Next: post-Engineer processing (step 5g post-return)` — then execute that step.

For each task:
1. Capture reflections (step 5m — see [dispatch-context-artifacts.md](dispatch-context-artifacts.md)).
2-7. Run **Post-Return Submission Gates** — see [dispatch-context-gates.md](dispatch-context-gates.md) for the full submission gate, dirty-exit detection, epic progress-note gate, rescue sweep, agent ID recording, and review-seed steps.

---

## 5h. Main Merge Before Tester

For each task, merge `main` into the worktree branch to incorporate any changes from companion tasks that landed on main in parallel. Process sequentially:

```bash
# For each task in _task_ids:
_path_var="_worktree_path_${_task_id}"
_worktree_path="${!_path_var}"
cd "${_worktree_path}"
git merge main --no-edit
```

If any merge fails due to conflicts for a specific task:
1. Report the conflicting files for that task.
2. Re-dispatch the Engineer for **only that task** to resolve the conflicts.
3. Remove the task from the Tester dispatch if merge remains unresolved. Do NOT hold up other tasks.

---

## 5i. Parallel Tester Dispatch

See [dispatch-context-prompts.md](dispatch-context-prompts.md) for the full Tester dispatch rules, diff preparation, prompt templates (epic, issue, minimal), and post-Tester cleanup.

For Tester model escalation: Track `_tester_output_failures_{_id}` -- how many times the Tester has returned no parseable verdict for this item (no DB review AND no verdict in text output). This is distinct from a legitimate FAIL verdict. Model escalation is handled by the Tester output gate's fallback chain in `engineer-tester-closeout.md` Step 9: retry 1 uses a minimal prompt (no inline diff) with the default model, retry 2 uses the minimal prompt with `model: "opus"`, and exhaustion falls back to conduct direct verification (see [dispatch-context-gates.md](dispatch-context-gates.md) section 5i-conduct-verify).

---

## 5o. Advance Status After PASS Verdict

After a PASS verdict, update statuses to reflect completion. The item-level and task-level status systems are distinct.

**Caller prerequisite:** Before calling step 5o for **issue items** (legacy note; `/yoke conduct` rejects issue items at entry), the caller MUST run the verification-requirement preflight: query coarse missing-pass requirements, satisfy the conduct-satisfiable ones from conduct evidence or sanctioned helpers, use `yoke qa screenshot-evidence satisfy --item YOK-{N}` (function id `qa.screenshot_evidence.satisfy`) for ACs tagged `[requires_screenshot_evidence]` once truthful browser evidence exists, then run `yoke qa gate-summary --item YOK-{N} --target reviewed-implementation` and halt if it fails. Conduct does **not** invoke the advance router here, so remaining browser and E2E blockers must already have truthful passing runs (or stay blocked). Epic items are handled in the simulation gate.

**Issue items:** Advance the backlog item from `reviewing-implementation` to `reviewed-implementation`.
Invoke the Yoke advance skill for `YOK-${_id}` with target `reviewed-implementation`.

**Epic tasks:** The `review_insert` call that recorded the PASS verdict auto-advances the task to `reviewed-implementation`. No manual status update needed. The epic **item** stays at `implementing` — individual task completions do not change the parent item status.

When all tasks in an epic are complete, the conduct skill reports this and the operator runs `/yoke merge` to transition the epic item.

the conduct skill does NOT run done-transition or merge engines. Done-transitions (PR creation, merge to main, status update, GitHub issue close, worktree cleanup) are handled by:
- **Issues:** `/yoke advance YOK-{N} done`
- **Epics:** `/yoke merge {epic-id}`

This separation ensures dispatch never closes GitHub issues or removes worktrees for unmerged items.

---

## 5p. Epic Auto-Chaining

**Context reset on chain advance:** When auto-chaining makes a new task eligible, do NOT carry forward the prior task's body (`_body`), context block, or Tester feedback (`_tester_feedback`) into the next iteration. Each task gets fresh context preparation in step 5f. This prevents stale context from prior chain segments from accumulating.

After a PASS verdict on an epic task, find the next dispatchable task in the dispatch chain. The chain advances sequentially, but **skips** tasks whose dependencies are not yet met instead of pausing the entire chain:

1. **Advance loop** — repeat until a dispatchable task is found or the queue is exhausted:

 a. Advance the dispatch chain to the next task:
 ```bash
 _advance_result=$(yoke workflow-item epic-dispatch-chain advance --epic "$_epic_id" --worktree "$_worktree_branch")
 ```
 On success, outputs `{new_index}|{next_task_num}`. On end-of-queue, exits 1.

 b. If `dispatch-chain-advance` exits 1 (end-of-queue): **break out of loop** — go to step 2.

 c. Parse the result:
 ```bash
 _next_index=$(printf '%s' "$_advance_result" | cut -d'|' -f1)
 _next_task=$(printf '%s' "$_advance_result" | cut -d'|' -f2)
 ```

 d. Check the next task's dependencies via the task read wrapper:
 ```bash
 _next_task_row=$(yoke workflow-item epic-task get --epic "$_epic_id" --task-num "$_next_task")
 ```

 e. **If dependencies are NOT met:** Set the task to `blocked`, note which deps are unmet, and **continue the loop** (advance again to try the next task in the queue).

 f. **If dependencies are met (or task has none):** This task is dispatchable. **Break out of loop** — go to step 3.

2. **End-of-queue reached (no dispatchable task found):** Check whether all tasks are complete or some are still blocked:
 - If all tasks are `done` or `reviewed-implementation`: the chain is complete. Do NOT run done-transition or merge engines directly. Do NOT update backlog item status. Do NOT close the GitHub issue. Do NOT remove the worktree. Note: "All tasks in this worktree complete. Run `/yoke merge {_epic_id}` to create PRs and merge to main." Mark `[x]`.
 - If some tasks are still `blocked` or `planned`: note which tasks remain and what blocks them. Treat the epic as partially complete for this invocation. Print the list of blocked tasks and their unmet dependencies so the operator knows what to unblock or reorder.

3. **Dispatchable task found:** The task becomes eligible for processing. Each chained task gets fresh context preparation.
