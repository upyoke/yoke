# Conduct — Engineer/Tester Closeout Protocol

Invoked from `engineer-tester-dispatch.md` after Tester returns. Covers Tester artifact capture, ephemeral teardown, temp file cleanup, verdict parsing, the Tester output gate, and verdict branching (PASS auto-chain / FAIL retry / FAIL exhausted).

**Inherited:** `SCRIPT_DIR`, `MAIN_ROOT`, `_epic_id`, `N`, `_task_id`, `_worktree_path`, `_worktree_branch`, `TASK_BASELINE`, `ATTEMPT_BASELINE`, `_max_attempts`, `_no_chain`, `_attempt`, `_tester_output_failures`, `_full_diff_file`, `_task_diff_file` (if size-gated), `_attempt_diff_file` (if size-gated), `_env_id` (if ephemeral env).

---

### Step 8 — After Tester Returns

**AUTONOMOUS CONTINUATION REQUIRED:** Emit `[CONTINUE] Tester returned for YOK-{N}. Next: verdict processing (S6g.9)` then execute immediately.

- Capture reflections (see `dispatch-context.md` step 5m; use `offset`/`limit`).
- Commit Tester artifacts (see `dispatch-context.md` step 5n; use `offset`/`limit`).
- **Ephemeral teardown (E5):** If `_env_id` was set:
 ```bash
 if [ -n "${_env_id}" ]; then
 yoke ephemeral-env update "${_env_id}" status "stopped"
 fi
 ```
- **Cleanup diff temp files:**
 ```bash
 rm -f "$_full_diff_file"
 rm -f "$_task_diff_file"
 rm -f "$_attempt_diff_file"
 ```
- **Release per-task work-claim** (fires on both PASS and FAIL — Step 9 may branch into a retry that re-acquires the claim at the next Engineer dispatch via [`engineer-tester-dispatch.md`](engineer-tester-dispatch.md) Step 3b). The release targets the exact `target_kind="epic_task"` claim acquired for this task at Step 3b/6b; it never touches the parent item claim. Failure is visible — do not fall back to releasing the parent item claim:
 ```bash
 if ! yoke claims work release \
   --epic-id "${_epic_id}" --task-num "${_task_id}" \
   --reason "tester return YOK-${N} task ${_task_id}"; then
  echo "WARN: failed to release epic_task claim for (epic_id=${_epic_id}, task_num=${_task_id})."
  echo "Inspect with 'python3 -m runtime.harness.harness_sessions who-claims YOK-${_epic_id}' before proceeding."
 fi
 ```

### Step 9 — Parse Verdict

- Check DB: `yoke workflow-item epic-task review-get --epic "$_epic_id" --task-num "$_task_id"`
- Fall back to text output for `VERDICT: PASS` / `VERDICT: FAIL`.
- **Auto-insert when verdict-only.** When the DB query returns "no review found" but the Tester's text response contains a clear `VERDICT: PASS` or `VERDICT: FAIL` line, run the review-insert yourself with a conduct-attributed body. Testers regularly return a text VERDICT line but skip the `epic review-insert` call; the conduct-side closeout is the single check that catches this. The body should record the verdict, name conduct as the inserter ("conduct-recorded after Tester returned text VERDICT but skipped review-insert"), and copy the Tester's per-AC summary inline so the review row is reviewable later. Command shape (after writing the body to `/tmp/yok-N-task-M-review.txt`):
 ```bash
 yoke workflow-item epic-task review-insert --epic "$_epic_id" --task-num "$_task_id" --verdict PASS --body-file /tmp/sun-${N}-task-${_task_id}-review.txt
 ```
 The auto-insert auto-advances status to `reviewing-implementation` → `reviewed-implementation` exactly as if the Tester had called it directly. Do NOT escalate to the Tester output gate when text VERDICT is present — that gate is reserved for the no-verdict-at-all case.
- **Load-bearing note:** the conduct-side closeout is the single check that catches Testers that emit a text VERDICT but skip `epic review-insert`. There is no SubagentStop hook gate enforcing review-row existence — the per-subagent binding the gate would have needed cannot be satisfied from the SubagentStop hook payload (subagents share the parent's session_id and inherit the main repo's `CLAUDE_PROJECT_DIR`), so the gate previously blocked every termination and was removed. The escalating strategy below is the same shape on Claude and Codex.
- If no verdict found AT ALL (neither review row nor text VERDICT): enter the **Tester output gate** (escalating strategy):

 a. **Increment `_tester_output_failures`.**

 b. **Retry 1 (`_tester_output_failures` == 1): Minimal prompt, default model.**
 Log: `Tester output gate: retrying YOK-{N} with minimal prompt (no inline diff)`
 Re-invoke Tester using the minimal prompt variant from `dispatch-context.md` step 5i-minimal. No `model: "opus"`. Run reflection capture and artifact commit, re-parse verdict.

 c. **Retry 2 (`_tester_output_failures` == 2): Minimal prompt + opus model.**
 Log: `Tester output gate: retrying YOK-{N} with minimal prompt + opus model`
 Re-invoke Tester using the minimal prompt variant from `dispatch-context.md` step 5i-minimal AND `model: "opus"`. Run reflection capture and artifact commit, re-parse verdict.

 d. **Exhaustion (`_tester_output_failures` > `MAX_TESTER_REPROMPTS`): Conduct direct verification.**
 Log: `Tester output gate exhausted: conduct verifying YOK-{N} directly`
 Follow the conduct skill direct verification procedure from `dispatch-context.md` step 5i-conduct-verify. Produce a synthetic PASS or FAIL verdict.

### Step 10 — Process Verdict

**On PASS:**
- The `review_insert` call auto-advanced the task to `reviewed-implementation`. No manual status update needed.
- Print structured summary:
 ```
 YOK-{N} task {_task_id} complete -- {task title}
 Status: reviewed-implementation (attempt {_attempt}/{_max_attempts})
 Epic: {_epic_id}
 Branch: {branch}
 Worktree: {_worktree_path}
 Commits: {count} new ({first_sha}..{last_sha})
 GitHub: {github_issue URL or "not synced"}
 ```
- **Auto-chaining** (see `dispatch-context.md` step 5p; use `offset`/`limit`, unless `_no_chain` is true):
 - Advance dispatch chain index. If next task's dependencies are NOT met, set it to `blocked` and keep advancing to find the next unblocked task.
 - If queue exhausted with no dispatchable task: report blocked tasks. If all tasks are terminal, **go to `simulation-gate.md`** (S6h).
 - If dispatchable task found and `_no_chain` is false: reset `_attempt=1`, `_tester_output_failures=0`, set `_task_id` to that task, reload task body and context, and **restart the loop** from S6f (re-read `entry-activation.md` S6f).
 - If `_no_chain` is true: stop after this task. Print:
 ```
 Chain stopped (--no-chain). Next task: {next-id} ({next-title}).
 ```
 **Go to `cleanup-report.md`** with `SUCCESS`.
- If all epic tasks are now `done` or `reviewed-implementation`: **Go to `simulation-gate.md`** (S6h).

**On FAIL (attempt < _max_attempts):**
- Store Tester feedback as `_tester_feedback`.
- Increment `_attempt`.
- Transition task back to `implementing`:
 ```bash
 yoke conduct epic-task update-status --epic "$_epic_id" --task-num "$_task_id" \
  --status implementing --note "Retry attempt ${_attempt} of ${_max_attempts}" --no-rebuild
 ```
- Update dispatch chain:
 ```bash
 yoke workflow-item epic-dispatch-chain update --epic "$_epic_id" --worktree "$_worktree_branch" \
  --field current_attempt --value "${_attempt}"
 ```
- Record new attempt baseline and **continue loop** (return to `engineer-tester-dispatch.md` Step 1).

**On FAIL (attempt >= _max_attempts):**
- Update task status through the conduct pipeline wrapper: `yoke conduct epic-task update-status --epic "$_epic_id" --task-num "$_task_id" --status failed --note "Exhausted attempts"`
- Print structured summary:
 ```
 YOK-{N} task {_task_id} failed -- {task title} (exhausted {_max_attempts} attempts)
 Status: failed
 Epic: {_epic_id}
 Branch: {branch}
 Worktree: {_worktree_path}
 GitHub: {github_issue URL or "not synced"}
 Action: Review Tester reports, adjust criteria, or re-run with --max-attempts N
 ```
- **Go to `cleanup-report.md`** with `HALTED`.
