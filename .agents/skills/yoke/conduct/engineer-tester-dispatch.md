# Conduct — Engineer/Tester Dispatch Protocol

Invoked from `engineer-tester-loop.md` S6g. Covers loop initialization, branch-ahead detection, attempt baseline, Engineer dispatch with submission gate, and Tester dispatch with diff size-gating.

**Inherited:** `MAIN_ROOT`, `_epic_id`, `N`, `_task_id`, `_worktree_path`, `_worktree_branch`, `TASK_BASELINE`, `_max_attempts`, `_no_chain`, context block, `_attempt`, `_tester_output_failures`.

---

### Loop Initialization

```
_attempt=1
_tester_output_failures=0
```

**Branch-ahead detection:** Before entering the loop, check if the worktree branch already has commits ahead of main for the current task. Compare against `TASK_BASELINE` — if `TASK_BASELINE == HEAD`, Engineer should still be dispatched. Read via the main checkout's branch ref because the per-task `epic_task` work-claim has not been acquired yet (Step 3b below does that); `lint_session_cwd` would otherwise block `git -C "${_worktree_path}"` against the lane worktree.

```bash
_worktree_head=$(git -C "${MAIN_ROOT}" rev-parse "${_worktree_branch}")
_has_implementation=false
if [ "$TASK_BASELINE" != "$_worktree_head" ]; then
 _has_implementation=true
fi
```

**Skip logic does NOT apply to subsequent tasks in an epic chain.** If `TASK_BASELINE` differs from the merge-base with main (prior tasks committed), always dispatch Engineer.

---

### Loop Steps (while `_attempt <= _max_attempts`)

**Step 1 — Record attempt baseline:** Read via the main checkout's branch ref — Step 3b's per-task claim acquire is still ahead, so direct lane-worktree access is blocked by `lint_session_cwd`.
```bash
ATTEMPT_BASELINE=$(git -C "${MAIN_ROOT}" rev-parse "${_worktree_branch}")
_progress_note_count_before=$(yoke db read --format lines "SELECT COUNT(*) FROM epic_progress_notes WHERE epic_id='${_epic_id}' AND task_num=${_task_id}" 2>/dev/null || echo 0)
```

**Step 2 — Skip Engineer if implementation already on branch:** If `_has_implementation` is true AND `_attempt` equals 1:
- Emit: `[SKIP] YOK-{N}: implementation already on branch, skipping to Tester`
- Seed review requirement: `yoke workflow-item epic-task review-seed --epic "$_epic_id" --task-num "$_task_id"`
- Go directly to Step 5 (Merge main).

On retry attempts (`_attempt > 1`), always dispatch Engineer.

**Step 3 — Run 5f-rehydrate** (see `dispatch-context.md`, ~line 640): Query prior progress notes and tester reviews for this epic task. Store as `_rehydration_block`. Use `offset`/`limit` to read only the `5f-rehydrate` section.

**Step 3b — Acquire per-task work-claim** (covers both Engineer and Tester dispatches for this task):

The parent item claim from `entry-activation.md` S3b is the epic coordination lock; the `target_kind="epic_task"` claim acquired here authorizes writes in the task worktree (`epic_tasks.worktree`). Same-session re-acquire is idempotent — see [`engineer-tester-loop.md`](engineer-tester-loop.md) "Re-entry semantics" for the cross-session paths.

```bash
yoke claims work acquire \
 --epic-id "${_epic_id}" --task-num "${_task_id}" \
 --reason "engineer dispatch YOK-${N} task ${_task_id}"
```

Verify the claim landed before dispatching — mirrors entry-activation S3b's verify-claim-exists invariant. This assertion uses the retained operator-debug raw SQL router because the registered claim acquire surface does not expose a same-row verification projection; never construct a DB path manually:

```bash
_eng_claim_ok=$(YOKE_SESSION_ID="${YOKE_SESSION_ID}" yoke db read --format lines \
 "SELECT 1 FROM work_claims WHERE session_id='${YOKE_SESSION_ID}' AND target_kind='epic_task' AND epic_id=${_epic_id} AND task_num=${_task_id} AND released_at IS NULL")
if [ -z "$_eng_claim_ok" ] || [ "$_eng_claim_ok" = "0" ]; then
 echo "HALT: engineer dispatch — no active epic_task claim for (epic_id=${_epic_id}, task_num=${_task_id}) under session ${YOKE_SESSION_ID}."
 echo "Recovery: run 'yoke claims work acquire --epic-id ${_epic_id} --task-num ${_task_id} --reason \"engineer dispatch\"' and retry."
 exit 1
fi
```

**HALT** if the verification returns empty. Do not proceed to Step 4 without a confirmed active per-task claim.

**Step 4 — Dispatch Engineer** (no isolation — uses Yoke-managed worktree):

**Dispatch:** descriptor `DispatchDescriptor(role="engineer")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `---SUBMISSION-CHECKS-START---`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 {If _attempt = 1: "Implement" | If _attempt > 1: "Retry"} YOK-{N}: {_title}
 {If _attempt > 1: "(attempt {_attempt} of {_max_attempts})"}

 {context block from S6f}

 Read the authoritative task spec from the DB before starting:
 yoke workflow-item epic-task body-get --epic "{_epic_id}" --task-num "{_task_id}"
 Also read the parent item spec for full context:
 yoke items get YOK-{N} spec

 {If _attempt > 1:
 The Tester found these issues on the previous attempt:
 {_tester_feedback}
 Fix all issues, commit, and ensure tests pass.}

 {If _rehydration_block is non-empty:}
 {_rehydration_block}

 {If _attempt = 1:
 IMPORTANT: cd to the worktree path FIRST before doing any work.
 Acceptance criteria are in the spec.
 Commit incrementally on the worktree branch.
 Run tests before finishing.

	 FILE BUDGET: read the `## File Budget` section in the parent item spec (and the task body for epic tasks) before creating or growing any authored file. Hard limit is 350 lines per authored file (owned by `yoke_core.domain.file_line_check`); design target is `<=300` lines. The budget lists the expected files and single responsibilities — split the work to fit existing entries before inventing new oversized modules, and surface mid-implementation when the budget is fundamentally unrealistic for the work rather than landing oversized files. End your durable submission receipt with `file_budget: PASS` (created or grew authored code AND every authored file is at or below 350 lines) or `file_budget: SKIP` (no authored code created or grown). The submission gate rejects missing, malformed, `FAIL`, or `UNKNOWN` values and re-dispatches the same attempt.

	 Apply the simplify three-axis vocabulary at code-author time. See AGENTS.md "## Simplify — three-axis doctrine": reuse existing surfaces first, keep the diff to the smallest AC-satisfying shape, justify new infrastructure against what already exists, and apply the future-concept lens when the change touches actors, sessions, heartbeats, ownership, leases, claims, approvals, overrides, evidence, run records, journals, packets, locks, or shared-state coordination.}

	 CODEBASE-READER NAMING: Assume future readers of the codebase will NOT have the ephemeral planning artifacts you are working from. Treat the task/spec/plan as scaffolding, not naming source material. New or renamed files, modules, helpers, tests, docs, commands, events, config keys, symbols, headings, and comments must describe current function, purpose, mechanics, or domain role to someone who can only see the repository. Do not copy ticket IDs, plan names, initiative labels, phase/task/thread numbers, AC/FR identifiers, branch/worktree names, or implementation-batch wording into live code or current-state docs unless the identifier is itself a runtime/domain concept.

	 {If task body/spec mentions schema, column, migration, ALTER TABLE, CREATE TABLE, ADD COLUMN, or DROP TABLE:
	 DB MIGRATION PROTOCOL: Follow the migration protocol in your agent definition (## DB Schema Changes section).}

 {If task body/spec mentions live DB, verify, CHECK constraint, deployed state, or any shared mutable system:
 LIVE-STATE AC FAIL-SAFE: ACs tagged [READ-ONLY] mean observe and report only. ACs tagged [APPLY-MUTATION] mean apply the change via the sanctioned write path. Untagged ACs referencing live/shared state MUST be treated as [READ-ONLY].}

 OUTPUT DISCIPLINE: Before final response, write a final progress note containing the required `---SUBMISSION-CHECKS-START---` block from your agent definition. Then return only a short summary (commit count, test status). Do not repeat spec text or acceptance criteria in your final output.
```

**Step 5 — After Engineer returns:**

**AUTONOMOUS CONTINUATION REQUIRED:** Emit `[CONTINUE] Engineer returned for YOK-{N}. Next: post-Engineer processing (S6g.5)` then execute immediately.

- Capture reflections (see `dispatch-context.md` step 5m; use `offset`/`limit`).
- **Submission gate:** Run `yoke workflow-item epic-task submission-receipt-get --epic "$_epic_id" --task-num "$_task_id" --after-note-count "$_progress_note_count_before"` and require it to pass. This is the load-bearing check on both Claude and Codex — there is no SubagentStop hook gate (the per-subagent binding required to identify a stopping engineer's `(epic_id, task_num)` cannot be satisfied from the SubagentStop hook payload). The command reads `---SUBMISSION-CHECKS-START---` / `---SUBMISSION-CHECKS-END---` from `epic_progress_notes.body`, not from the Agent result summary. Required keys: `test_plan`, `files_touched`, `edited_tests`, `clean_worktree`, `progress_notes`, `file_budget`. Accept only `PASS` or explicit `SKIP` for `test_plan`, `files_touched`, `edited_tests`. Require `clean_worktree: PASS`. Require `progress_notes: PASS` when `HEAD` differs from `ATTEMPT_BASELINE`; `SKIP` only when no commit landed. Require `file_budget: PASS` when the submission created or grew authored code (every authored file is at or below 350 lines per `yoke_core.domain.file_line_check`); `file_budget: SKIP` is valid only when no authored code was created or grown (e.g., docs-only sub-task). Missing line, malformed line, or any `FAIL`/`UNKNOWN` value re-dispatches the same attempt. On any failure, re-dispatch Engineer for the same attempt (do NOT increment `_attempt`).
- **Dirty-exit detection:**
 ```bash
 _last_commit_subject=$(git -C "${_worktree_path}" log -1 --format='%s' 2>/dev/null || true)
 ```
 If `_last_commit_subject` matches `chore: auto-commit Engineer uncommitted work [YOK-${N}]`, re-dispatch Engineer for the same attempt. Do NOT advance to `reviewing-implementation` from a safety-net commit.
- **Epic progress-note gate:**
 ```bash
 _progress_note_count_after=$(yoke db read --format lines "SELECT COUNT(*) FROM epic_progress_notes WHERE epic_id='${_epic_id}' AND task_num=${_task_id}" 2>/dev/null || echo 0)
 _head_after_engineer=$(git -C "${_worktree_path}" rev-parse HEAD 2>/dev/null || true)
 ```
 If `_head_after_engineer` differs from `ATTEMPT_BASELINE` and `_progress_note_count_after` not greater than `_progress_note_count_before`, re-dispatch Engineer for the same attempt.
- **Post-Engineer rescue sweep:**
 ```bash
 cd {_worktree_path}
 git add -A 2>/dev/null
 if ! git diff --cached --quiet 2>/dev/null; then
 _uncommitted_count=$(git diff --cached --name-only | wc -l | tr -d ' ')
 _uncommitted_files=$(git diff --cached --name-only | tr '\n' ', ' | sed 's/,$//')
 git commit -m "chore: auto-commit Engineer uncommitted work [YOK-${N}]"
 echo "Warning: Engineer left ${_uncommitted_count} uncommitted file(s) in worktree."
 yoke ouroboros entry insert \
 --agent conduct --category problem --context "YOK-${N}" \
 --observation "Engineer left ${_uncommitted_count} uncommitted file(s) in worktree for YOK-${N}. Files: ${_uncommitted_files}"
 fi
 ```
 If this sweep committed anything, re-dispatch Engineer for the same attempt.
- **Seed review:** `yoke workflow-item epic-task review-seed --epic "$_epic_id" --task-num "$_task_id"` (auto-advances to `reviewing-implementation`).

**Step 6 — Merge main:**
```bash
cd {_worktree_path}
git merge main --no-edit
```
If merge fails: re-dispatch Engineer to resolve conflicts, then retry merge.

**Step 6b — Verify per-task claim before Tester dispatch.** The claim acquired at Step 3b should still be held; re-acquire is idempotent and acts as the verify step. Same shape as Step 3b's verification:

```bash
yoke claims work acquire \
 --epic-id "${_epic_id}" --task-num "${_task_id}" \
 --reason "tester dispatch YOK-${N} task ${_task_id}"
_tester_claim_ok=$(YOKE_SESSION_ID="${YOKE_SESSION_ID}" yoke db read --format lines \
 "SELECT 1 FROM work_claims WHERE session_id='${YOKE_SESSION_ID}' AND target_kind='epic_task' AND epic_id=${_epic_id} AND task_num=${_task_id} AND released_at IS NULL")
if [ -z "$_tester_claim_ok" ] || [ "$_tester_claim_ok" = "0" ]; then
 echo "HALT: tester dispatch — no active epic_task claim for (epic_id=${_epic_id}, task_num=${_task_id}) under session ${YOKE_SESSION_ID}."
 echo "Recovery: re-run conduct or 'yoke claims work acquire --epic-id ${_epic_id} --task-num ${_task_id}'."
 exit 1
fi
```

**HALT** if verification returns empty. Do not proceed to Step 7 without a confirmed active per-task claim.

**Step 7 — Dispatch Tester:**

**No manual diff truncation.** Never truncate or summarize diffs with `...`. Use size-gate.

```
TESTER_DIFF_INLINE_MAX_LINES=300
```

Size-gate the per-task diff:
```bash
_task_diff_line_count=$(git -C "${_worktree_path}" diff "${TASK_BASELINE}..HEAD" | wc -l | tr -d ' ')
if [ "$_task_diff_line_count" -gt "$TESTER_DIFF_INLINE_MAX_LINES" ]; then
 _task_diff_file=$(mktemp)
 git -C "${_worktree_path}" diff "${TASK_BASELINE}..HEAD" > "$_task_diff_file"
 _task_diff_stat=$(git -C "${_worktree_path}" diff "${TASK_BASELINE}..HEAD" --stat)
else
 _task_diff=$(git -C "${_worktree_path}" diff "${TASK_BASELINE}..HEAD")
fi
```

Full diff to temp file:
```bash
_full_diff_file=$(mktemp)
git -C "${_worktree_path}" diff main...HEAD > "$_full_diff_file"
```

Per-attempt retry diff size-gate (on retry `_attempt > 1`):
```bash
_attempt_diff_line_count=$(git -C "${_worktree_path}" diff "${ATTEMPT_BASELINE}..HEAD" | wc -l | tr -d ' ')
if [ "$_attempt_diff_line_count" -gt "$TESTER_DIFF_INLINE_MAX_LINES" ]; then
 _attempt_diff_file=$(mktemp)
 git -C "${_worktree_path}" diff "${ATTEMPT_BASELINE}..HEAD" > "$_attempt_diff_file"
 _attempt_diff_stat=$(git -C "${_worktree_path}" diff "${ATTEMPT_BASELINE}..HEAD" --stat)
else
 _attempt_diff=$(git -C "${_worktree_path}" diff "${ATTEMPT_BASELINE}..HEAD")
fi
```

Tester prompt template:

**Dispatch:** descriptor `DispatchDescriptor(role="tester", extras=(("model","opus"),) if _tester_output_failures >= 2 else ())` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `VERDICT: PASS|FAIL`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Validate YOK-{N}: {_title}

 Read the authoritative task spec from the DB before validating:
 yoke workflow-item epic-task body-get --epic "{_epic_id}" --task-num "{_task_id}"
 Also read the parent item spec for full context:
 yoke items get YOK-{N} spec

 IMPORTANT: Use absolute paths and module invocations. Shell variables do NOT persist across Bash tool calls.

 {For epics: interface contracts from dependency tasks}
 {For epics: downstream task bodies for path-tracing}

 {If per-task diff was NOT size-gated (_task_diff exists):}
 Engineer's changes for this task (diff from task start):
 {_task_diff}

 {If per-task diff WAS size-gated (_task_diff_file exists):}
 Engineer's changes for this task ({_task_diff_line_count} lines, diff from task start):
 {_task_diff_stat}
 Per-task diff ({_task_diff_line_count} lines) written to: {_task_diff_file}

 {On retry where per-attempt diff was NOT size-gated:}
 Engineer's changes this attempt only (diff from attempt start):
 {_attempt_diff}

 {On retry where per-attempt diff WAS size-gated:}
 Engineer's changes this attempt only ({_attempt_diff_line_count} lines):
 {_attempt_diff_stat}
 Per-attempt diff written to: {_attempt_diff_file}

 Full branch diff (all tasks from main) is available at: {_full_diff_file}

	 Regression detection: Compare failing test NAMES between main and the branch —
	 not just counts. A test that passes on main but fails on the branch is a regression.

	 Review the engineer's work against the acceptance criteria in the spec.
	 Check codebase-reader naming: new or renamed surfaces must describe current function/purpose/mechanics rather than the ticket, plan, phase, task, AC, branch, worktree, or batch that produced them.
	 Run tests. Return a verdict line:
 VERDICT: PASS or VERDICT: FAIL followed by details.

 OUTPUT DISCIPLINE: End with VERDICT line and a brief summary.
```

---

**Handoff:** After Tester returns, read and follow `.agents/skills/yoke/conduct/engineer-tester-closeout.md` for verdict processing and auto-chaining.
