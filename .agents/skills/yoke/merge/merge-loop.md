# Merge — Per-Branch Merge Loop

Covers merge Step 6: the per-branch sequential merge loop. For each branch, resolves the actual branch, commits any Tester artifacts, invokes the retained merge watcher (`python3 -m yoke_core.tools.watch_merge merge-worktree`), updates task status, re-verifies ACs post-merge on main, and halts on regression.

**Context variables** (set by the Preflight phase): `{epic-id}`, `WORKTREE_PATH`, `ACTUAL_BRANCH`.

---

6. **For each branch, sequentially:**

 **Pre-merge: resolve actual branch and commit any uncommitted Tester artifacts.** The stored branch name may be stale. Resolve the worktree path, then verify the actual checked-out branch before merging:
 ```bash
 WORKTREE_PATH=".worktrees/$(echo {branch} | tr '/' '-')"
 ACTUAL_BRANCH="{branch}"
 if [ -d "$WORKTREE_PATH" ]; then
 _actual=$(git -C "$WORKTREE_PATH" branch --show-current 2>/dev/null)
 if [ -n "$_actual" ] && [ "$_actual" != "{branch}" ]; then
 echo "Warning: branch mismatch — stored '{branch}', actual '$_actual'. Using actual." >&2
 ACTUAL_BRANCH="$_actual"
 fi
 git -C "$WORKTREE_PATH" add -A 2>/dev/null
 git -C "$WORKTREE_PATH" diff --cached --quiet || git -C "$WORKTREE_PATH" commit -m "chore: commit Tester review artifacts before merge [$ACTUAL_BRANCH]"
 fi
 ```

 **Merge:**
 ```bash
 # Pass --force-lock and --skip-simulation if user specified them
 _merge_flags=""
 if [ "${FORCE_LOCK:-0}" -eq 1 ]; then _merge_flags="--force-lock"; fi
 if [ "${SKIP_SIMULATION:-0}" -eq 1 ]; then _merge_flags="$_merge_flags --skip-simulation"; fi
 python3 -m yoke_core.tools.watch_merge merge-worktree -- $_merge_flags "$ACTUAL_BRANCH" main {epic-id}
 ```
 Note: `{epic-id}` is passed as the epic ID (third argument) for DB-native prereq checks. `--force-lock` is passed through if the user specified it.

 This script:
 - Rebases onto the updated main
 - Auto-resolves generated files (lock files, compiled output)
 - Runs tests
 - Creates a PR via PAT-backed REST (`yoke_core.engines.merge_worktree_pr_rest`)
 - Waits for CI to pass
 - Merges via PAT-backed REST
 - Removes the worktree

 **If merge succeeds:**
 - For each task in the merged worktree, update its status to `done` using the merge pipeline's internal status writer. This is not the normal agent-facing product flow; the public `workflow-item epic-task update-status` wrapper intentionally refuses terminal success statuses.
 ```bash
 # Internal merge-admin fallback only; merge_worktree handles completed tasks automatically.
 YOKE_CLAIM_BYPASS="merge:PR-{pr-number}" YOKE_TASK_DONE_VERIFIED=1 python3 -m yoke_core.domain.update_status {epic-id} {task-num} done "Merged via PR #{pr-number}"
 ```
 This handles: DB update, GitHub label sync, **and closing the task's GitHub issue** (the script auto-closes issues when status reaches `done`).
 Note: `python3 -m yoke_core.tools.watch_merge merge-worktree` already handles this automatically for completed tasks in the worktree branch. Only manually call this internal fallback for tasks that were missed.

 - **Post-merge AC re-verification:** After task status updates and before continuing to the next branch, re-verify the epic-level acceptance criteria against the merged result on main (not the pre-merge worktree). This catches cases where auto-resolve discarded branch changes that satisfied ACs.

 **Step 1: Sync local main with origin.** Pull the PR merge commits so local main reflects the actual merged state:
 ```bash
 git pull --rebase origin main
 ```
 If the pull fails, skip AC re-verification and report the pull failure as the primary issue — do not halt the merge sequence for a pull failure (this aligns with existing Post-merge phase behavior).

 **Step 2: Re-verify ACs against main.** Read the same `### Acceptance Criteria` section from the backlog item body that was verified in the Preflight phase. For each AC:

 - **Statically verifiable ACs** (file existence, grep for strings, code patterns): Re-run the same check, but this time against the main working directory (the current checkout, which now contains the merged result after `git pull`). Do NOT use worktree paths — the worktree may have been removed by the merge watcher.

 - **Runtime-only ACs** (e.g., "the server starts without errors", "tests pass", behavioral checks that require execution): Skip with a note:
 ```
 AC-{i}: SKIP (runtime-only — cannot verify statically post-merge)
 ```

 **Print progress and results** for each AC, matching the Preflight phase format:
 ```
 Post-merge verifying AC {i}/{total}: {AC text (first 80 chars)}...
 AC-{i}: PASS (post-merge)
 ```

 **Step 3: Halt on regression.** If any statically verifiable AC that passed in the pre-merge Preflight phase check now fails post-merge, **halt the merge sequence immediately** and report:
 ```
 ┌─────────────────────────────────────────────────┐
 │ POST-MERGE AC REGRESSION DETECTED │
 ├─────────────────────────────────────────────────┤
 │ AC-{i}: {AC text} │
 │ Pre-merge: PASS (verified in worktree) │
 │ Post-merge: FAIL — {specific reason} │
 │ │
 │ The merge auto-resolve may have discarded │
 │ branch changes. Check the conflicting files │
 │ and re-apply if needed. │
 │ │
 │ Merged PR: #{pr-number} │
 │ Branch: {branch-name} │
 └─────────────────────────────────────────────────┘
 ```
 Do NOT continue to the next branch. The operator must investigate and fix the regression before proceeding.

 **Print a summary after all post-merge ACs:**
 ```
 Post-merge AC verification: {pass_count}/{verifiable_count} passed, {skip_count} skipped (runtime-only)
 ```

 If no `### Acceptance Criteria` section exists in the backlog item body, skip this step silently (the warning was already emitted in the Preflight phase).

 - Continue to the next branch

 **If merge fails (test failure after rebase):**
 - Pause the merge sequence
 - Report which tests failed and why
 - Create a backlog item: `/yoke idea "Integration fix: {branch} after merge"`
 - Tell the user to dispatch the integration-fix item, then re-run `/yoke merge`
