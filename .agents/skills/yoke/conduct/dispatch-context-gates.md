# Dispatch Context — Gates and Pre-Conditions

Extracted from `dispatch-context.md`. Contains gates, pre-conditions, and validation steps that run before or after dispatch.

---

## 5f-epic.1. Epic Sync Gate

Query the epic name from the item:
```bash
_epic_id="${_id}" # For epics, the item's own ID is the epic_id in epic_tasks
```

**Determine if the epic is synced.** An epic is considered "synced" when BOTH conditions are met: (a) dispatch chains exist, AND (b) at least one `epic_tasks` row has a non-null, non-empty `github_issue` field.

```bash
# Check condition (a): dispatch chains exist
_chains=$(yoke workflow-item epic-dispatch-chain list --epic "$_epic_id")

# Check condition (b): at least one task has a github_issue
_synced_task_count=$(python3 -m yoke_core.cli.db_router query "SELECT COUNT(*) FROM epic_tasks WHERE epic_id='$_epic_id' AND github_issue IS NOT NULL AND github_issue <> ''")
```

**If the epic is already synced** (`_chains` is non-empty AND `_synced_task_count > 0`): proceed to step 5f-epic.2.

**If the epic is NOT synced** (no chains OR `_synced_task_count` is 0):

1. **Pre-check: tasks must exist.** Query the task count:
 ```bash
 _task_count=$(python3 -m yoke_core.cli.db_router query "SELECT COUNT(*) FROM epic_tasks WHERE epic_id='$_epic_id'")
 ```
 If `_task_count` is 0, there are no tasks to sync. HALT with:
 > No epic tasks found for YOK-{_id}. Run `/yoke plan YOK-{_id}` first.

2. **Auto-sync:** Print `Epic YOK-{_id} not yet synced to GitHub. Running sync automatically...` and invoke the registered GitHub sync surface:
 ```bash
 yoke items github-sync "$_epic_id"
 ```

3. **Advance status to implementing** (activating the epic for conduct): invoke the Yoke advance skill for `YOK-${_id}` with target `implementing`.

4. **Commit sync changes:**

 Sync work is often DB-only or generated-view-only and may leave no tracked git diff.
 This is a valid success path — do NOT treat "nothing to commit" as a failure.
 If legacy root DB files appear in `data/`, stop and investigate; they should not be recreated.
 Never stage or commit generated views (e.g., `.yoke/BOARD.md`) as part of the auto-sync path.

 ```bash
 # Ensure generated views are not accidentally staged
 git reset HEAD -- .yoke/BOARD.md 2>/dev/null || true
 # Commit only if real tracked changes remain
 git diff --cached --quiet || git commit -m "YOK-${_id}: auto-sync — planned to implementing"
 ```

 If `git diff --cached --quiet` exits 0 (no tracked staged changes), that is fine — sync succeeded
 via DB and GitHub state updates. Proceed to post-sync verification.

5. **Post-sync verification:** Re-check that dispatch chains now exist and tasks have `github_issue` values:
 ```bash
 _chains=$(yoke workflow-item epic-dispatch-chain list --epic "$_epic_id")
 _synced_task_count=$(python3 -m yoke_core.cli.db_router query "SELECT COUNT(*) FROM epic_tasks WHERE epic_id='$_epic_id' AND github_issue IS NOT NULL AND github_issue <> ''")
 ```
 If `_chains` is still empty OR `_synced_task_count` is still 0: sync failed. HALT with:
 > Auto-sync failed for YOK-{_id}. Run `/yoke resync YOK-{_id}` manually.

6. **Print sync summary** (the retained sync bridge output already includes created/skipped counts). Print `Auto-sync complete for YOK-{_id}. Proceeding with dispatch.`

---

## 5f-epic.2a. Simulation Gap Gate

On the **first task dispatch** for an epic, check whether the plan-phase simulation report contains unresolved CRITICAL gaps. This is a read-only gate (no DB writes except `conduct-phase` for blocked items).

**1. First-dispatch detection:**

Query `epic_tasks` to determine if any task has progressed past initial state:
```bash
_non_pending=$(python3 -m yoke_core.cli.db_router query "SELECT COUNT(*) FROM epic_tasks WHERE epic_id='$_epic_id' AND status NOT IN ('planning','planned')")
```
If `_non_pending > 0`, skip the gate entirely -- this epic has already been evaluated on a prior dispatch.

**2. Simulation report lookup:**

Query the plan-phase simulation report:
```bash
_sim_output=$(yoke workflow-item epic-task simulation-get --epic "$_epic_id" --phase plan 2>/dev/null)
```
If the command exits with code 1 or returns empty output, pass silently (graceful degradation for pre-simulation epics). Proceed to the next step.

**3. Critical gap detection:**

Extract the body field (field 5, pipe-delimited) from `_sim_output` and search for lines containing `[CRITICAL]` (case-sensitive):
```bash
_sim_body=$(echo "$_sim_output" | awk -F'|' '{print $5}')
_critical_lines=$(echo "$_sim_body" | grep '\[CRITICAL\]' || true)
_critical_count=$(echo "$_critical_lines" | grep -c '\[CRITICAL\]' || true)
```

**4. Decision:**

- **If `_critical_count > 0` and neither `--force` nor `--ignore-gaps` was passed:**
 Print the gap list:
 ```
 Simulation Gap Gate: {_critical_count} unresolved CRITICAL gap(s) found for epic {_epic_id}:
 {_critical_lines}
 ```
 Print:
 > Dispatch blocked: {_critical_count} unresolved CRITICAL simulation gap(s) found. Use --force or --ignore-gaps to override.

 HALT with the gap list. Do not proceed with dispatch.

- **If `_critical_count > 0` and `--force` or `--ignore-gaps` was passed:**
 Print the gap list, then print:
 > WARNING: Overriding {_critical_count} CRITICAL simulation gap(s) via {flag-name}.

 Where `{flag-name}` is whichever flag was provided (`--force` or `--ignore-gaps`). Proceed with dispatch.

- **If `_critical_count = 0` (no critical gaps, or only WARNING/NOTE gaps):**
 Proceed silently.

---

## 5f-epic.3. Same-Worktree Dispatch Protection

Before proceeding, check if another task in the **same worktree** is already implementing or in review. Query the dispatch chain for this worktree -- if `current_task` refers to a different task than `_task_id` and that task's status is `implementing` or `reviewing-implementation` (use `yoke epic-tasks list --epic "$_epic_id"` when the full task list is sufficient; the exact dispatch-chain lookup is a retained internal boundary), **HALT:**

> Cannot dispatch task {_task_id}: task {other-id} is already implementing in worktree {worktree}. Wait for it to complete.

---

## 5f-epic.4. Verify Dependencies and Interface Contracts

Query the task's dependencies and check their statuses:
```bash
yoke epic-tasks list --epic "$_epic_id"
```
For each task in `dependencies`, check that its status is `done` or `reviewed-implementation` via `yoke epic-tasks list --epic "$_epic_id"` (or the retained internal task lookup when a single-row projection is required). If any dependency is not met, HALT with the unmet dependency details.

For each "Expects" contract in the task body, check that the providing task is completed and the expected files/exports exist.

---

<!-- Sections below extracted to child files -->
<!-- 5f-project-ephemeral + Browser QA: [dispatch-context-ephemeral.md](dispatch-context-ephemeral.md) -->
<!-- 5i-conduct-verify: [dispatch-context-verify.md](dispatch-context-verify.md) -->

## 5g Post-Return Submission Gates (steps 2-7)

These gates run after each Engineer returns, before advancing to Tester dispatch.

2. **Submission gate:** Read the Engineer's durable receipt from `epic_progress_notes`; do not trust the Agent tool result summary.
 ```bash
 yoke workflow-item epic-task submission-receipt-get --epic "$_epic_id" --task-num "$_task_id" --after-note-count "$_progress_note_count_before_{_id}"
 ```
 - Require a `---SUBMISSION-CHECKS-START---` / `---SUBMISSION-CHECKS-END---` block in a progress note created after `_progress_note_count_before_{_id}`.
 - Required keys: `test_plan`, `files_touched`, `edited_tests`, `clean_worktree`, `progress_notes`, `file_budget`.
 - Accept only `PASS` or explicit `SKIP` for `test_plan`, `files_touched`, and `edited_tests`.
 - Require `clean_worktree: PASS`.
 - For epic items, require `progress_notes: PASS` whenever `HEAD` differs from `ATTEMPT_BASELINE_{_id}`; only `SKIP` when no new commit landed during this attempt. For issue items, require an explicit skip reason.
 - Require `file_budget: PASS` when the submission created or grew authored code and every authored file is at or below 350 lines per `runtime/api/domain/file_line_check.py`; `file_budget: SKIP` is valid only when no authored code was created or grown. Missing, malformed, `FAIL`, or `UNKNOWN` values fail the gate.
 - If the receipt command exits nonzero because the block is missing, any key is missing, or any required line is `FAIL` / malformed / `UNKNOWN`, immediately re-dispatch Engineer for that same item and same attempt using the **submit-only remediation contract**. Do NOT increment `_attempt_{_id}`; this is submission-discipline remediation, not a Tester retry.

 **Submit-only remediation contract:** When re-dispatching Engineer for a failed submission, the remediation prompt MUST include these constraints:
 - **Scope:** This is a submission-only remediation pass, NOT a full implementation retry. The Engineer must finish submission for the existing branch state only.
 - **Allowed:** Commit any remaining work, add the missing progress note if required, write the `---SUBMISSION-CHECKS-START---` block into that progress note, and stop.
 - **Forbidden:** Starting new implementation, new exploration, new test creation, or opportunistic refactors. The branch state from the prior attempt is the deliverable.
 - **Budget:** This remediation pass is bounded to a short submission-only retry equivalent to 20 turns. The prompt must say: `This is a bounded submission-only remediation (max 20 turns). Do NOT start new work.`
 - **Failure reason:** The remediation prompt must state exactly which submission check failed (missing block, missing key, FAIL line, missing progress note, safety-net auto-commit, or rescue sweep) so Engineer can address only that deficiency.
 - This contract applies to ALL submission-gate failure cases: missing submission block (step 2), dirty-exit detection (step 3), epic progress-note gate (step 4), and post-Engineer rescue sweep (step 5).
3. **Dirty-exit detection:** Safety-net auto-commits are crash recovery, not a valid submission path.
 ```bash
 _last_commit_subject_{_id}=$(git -C "${_worktree_path}" log -1 --format='%s' 2>/dev/null || true)
 ```
 If `_last_commit_subject_{_id}` matches `chore: auto-commit Engineer uncommitted work [YOK-${_id}]` (with or without the `SubagentStop safety net` suffix), immediately re-dispatch Engineer for that same item and same attempt. Do NOT advance the item to `reviewing-implementation` or Tester from a safety-net commit.
4. **Epic progress-note gate:** For epic items, commits without a new progress note are a failed submission.
 ```bash
 _progress_note_count_after_{_id}=$(python3 -m yoke_core.cli.db_router query "SELECT COUNT(*) FROM epic_progress_notes WHERE epic_id='${_epic_id}' AND task_num=${_task_id}" 2>/dev/null || echo 0)
 _head_after_engineer_{_id}=$(git -C "${_worktree_path}" rev-parse HEAD 2>/dev/null || true)
 ```
 If `_head_after_engineer_{_id}` differs from `ATTEMPT_BASELINE_{_id}` and `_progress_note_count_after_{_id}` is not greater than `_progress_note_count_before_{_id}`, immediately re-dispatch Engineer for that same item and same attempt. Do NOT advance the item to `reviewing-implementation`.
5. **Post-Engineer rescue sweep:** For each item, run a rescue sweep on its worktree only to preserve unexpected dirty state the Engineer left behind. Unlike the older behavior, this sweep is a blocker: if it has to commit anything, do NOT continue to `reviewing-implementation`:
 ```bash
 cd {_worktree_path}
 git add -A 2>/dev/null
 if ! git diff --cached --quiet 2>/dev/null; then
 _uncommitted_count=$(git diff --cached --name-only | wc -l | tr -d ' ')
 _uncommitted_files=$(git diff --cached --name-only | tr '\n' ', ' | sed 's/,$//')
 git commit -m "chore: auto-commit Engineer uncommitted work [YOK-${_id}]"
 echo "Warning: Engineer left ${_uncommitted_count} uncommitted file(s) in worktree. Auto-committed as safety net."
 echo "Files: ${_uncommitted_files}"

 # Create Ouroboros entry to track the pattern
 yoke ouroboros entry insert \
 --agent conduct --category problem --context "YOK-${_id}" \
 --observation "Engineer left ${_uncommitted_count} uncommitted file(s) in worktree for YOK-${_id}. Auto-committed by conduct post-Engineer sweep. Files: ${_uncommitted_files}"

 # Write synthetic progress note so cold-start sessions have context
 if [ -n "$_epic_id" ] && [ -n "$_task_id" ]; then
 _max_note=$(python3 -m yoke_core.cli.db_router query "SELECT COALESCE(MAX(note_num), 0) FROM epic_progress_notes WHERE epic_id='${_epic_id}' AND task_num=${_task_id}" 2>/dev/null) || _max_note=0
 _next_note=$(( _max_note + 1 ))
 _commit_hash=$(git rev-parse --short HEAD 2>/dev/null) || true
 _ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
 printf '%s\n' "## Progress: Task #${_task_id} — Safety-net auto-commit
**Timestamp:** ${_ts}
**Commit:** ${_commit_hash:-unknown}
**Summary:** Engineer exited with uncommitted work. Auto-committed by conduct post-Engineer sweep.
**Files:** ${_uncommitted_files}" | python3 -m yoke_core.cli.db_router epic progress-note-insert "$_epic_id" "$_task_id" "$_next_note" 2>/dev/null || true
 fi
 fi
 ```
 If this sweep created a commit, immediately re-dispatch Engineer for that same item and same attempt. Do NOT update status to `reviewing-implementation`.
6. For epics, record agent ID: `yoke workflow-item epic-task metadata-update --epic "$_epic_id" --task-num "$_task_id" --fields-json '{"agent_id":"ENGINEER_AGENT_ID"}'`
7. **Seed task-level review requirement** (idempotent). `review_seed` now auto-advances epic tasks to `reviewing-implementation`:
 - **Epic only:** `yoke workflow-item epic-task review-seed --epic "$_epic_id" --task-num "$_task_id"`
 - **Issue:** invoke the Yoke advance skill for `YOK-${_id}` with target `reviewing-implementation`.

---
