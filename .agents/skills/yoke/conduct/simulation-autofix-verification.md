# Simulation Auto-Fix — Verification Protocol (AF10–AF19)

Amend Cycle. Invoked from `simulation-autofix-patching.md` when code-level gaps remain. Creates a fix task, dispatches Engineer/Tester, and re-simulates. Maximum 1 amend cycle.

**Inherited:** `MAIN_ROOT`, `_epic_id`, `_item_id`, `_worktree_path`, `_worktree_branch`, `_max_attempts`, `_code_level_gaps`.

**Returns:** `AUTOFIX_CLEAN` or `AUTOFIX_HALTED`.

---

### AF10. Parse Remaining Gaps

Read the latest simulation report:
```bash
_latest_sim=$(yoke workflow-item epic-task simulation-get --epic "$_epic_id" --phase integration)
```

Cross-reference with `_code_level_gaps` accumulated across all Architect iterations. Filter to CRITICAL/WARNING gaps with concrete fix guidance referencing code changes.

### AF10a. Extract Dependencies from Gap Source Tasks

Parse "Tasks involved" fields from all code-level gaps. Simulator outputs formats: `#7, #9`, `#007`, `Task 7`, plain `7`.

```
_dep_task_nums = empty set

For each code-level gap in _code_level_gaps:
 1. Find "Tasks involved:" line (case-insensitive).
 2. Extract task number references (#NNN, #N, Task N, Task NNN, plain N).
 3. Add each numeric value to _dep_task_nums.

Remove duplicates from _dep_task_nums.
```

After determining `_fix_task_num` in AF11, remove self-references from `_dep_task_nums`, then format:
```
_fix_deps = join(sorted(zero_pad_3(n) for n in _dep_task_nums if n != _fix_task_num), ",")
```
If no parseable task numbers: set `_fix_deps = ""` (graceful degradation).

### AF11. Create Fix Task

```bash
_max_task=$(python3 -m yoke_core.cli.db_router query "SELECT MAX(task_num) FROM epic_tasks WHERE epic_id='$_epic_id'")
_fix_task_num=$(printf "%03d" $((_max_task + 1)))
```

Remove self-references from `_dep_task_nums`, format `_fix_deps`, write the task body to a temp file, then insert through the registered epic-task add surface:
```bash
yoke workflow-item epic-task add --epic "$_epic_id" \
 --title "Fix integration simulation gaps" \
 --worktree "$_worktree_branch" \
 --context-estimate "M" \
 --dependencies "$_fix_deps" \
 --body-file "$_fix_task_body_file"
```

Write task body (template):
```
---
worktree: {_worktree_branch}
context_estimate: M
---
# Task {_fix_task_num}: Fix integration simulation gaps

## Description
Auto-created by the conduct skill's simulation auto-fix flow to address code-level
integration gaps that the Architect could not resolve at the plan level.

## Gaps to Fix
### GAP #{n}: {title}
- **Severity:** {severity}
- **Root cause:** {root cause from report}
- **Fix guidance:** {fix guidance from report}
- **Files:** {files mentioned in fix guidance}

## Acceptance Criteria
- [ ] AC-{n}: Gap #{n} is resolved with the expected behavior from the fix guidance

## Test Plan
- Run existing test suite to verify no regressions
- Verify each gap's fix guidance is implemented correctly

## Files Touched
{derived from gap fix guidance}
```

```bash
yoke workflow-item epic-task update-status --epic "$_epic_id" --task-num "$_fix_task_num" --status planned
yoke workflow-item epic-task history-insert --epic "$_epic_id" --task-num "$_fix_task_num" \
 --from-status none --to-status planned --note "Created by conduct auto-fix (amend cycle)"
yoke workflow-item epic-task file-add --epic "$_epic_id" --task-num "$_fix_task_num" \
 --file-path "{file_path}" --action modify
```

### AF12. Sync Fix Task to GitHub

```bash
yoke items github-sync "$_epic_id"
```

Already-synced tasks are skipped idempotently. Only the new fix task gets a GitHub issue created.

### AF13. Update Dispatch Chain

Append `_fix_task_num` to the dispatch chain queue:
```bash
_chain_row=$(yoke workflow-item epic-dispatch-chain get --epic "$_epic_id" --worktree "$_worktree_branch")
# Parse current queue JSON (field 5 of pipe-delimited row), append _fix_task_num
yoke workflow-item epic-dispatch-chain update --epic "$_epic_id" --worktree "$_worktree_branch" \
 --field queue --value "{updated_queue_json}"
yoke workflow-item epic-dispatch-chain update --epic "$_epic_id" --worktree "$_worktree_branch" \
 --field last_updated --value "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
```

### AF14. Dispatch Engineer for Fix Task

```bash
# Bypass claim verification for system-owned fix task through the conduct pipeline wrapper.
yoke conduct epic-task update-status --epic "$_epic_id" --task-num "$_fix_task_num" \
 --status implementing --note "Dispatched by conduct auto-fix (amend cycle)" \
 --no-rebuild --claim-bypass "simulation-autofix:epic-$_epic_id"
ATTEMPT_BASELINE_fix=$(git -C "${_worktree_path}" rev-parse HEAD)
```

Build context block (same pattern as `dispatch-context.md` 5f-epic.6) then dispatch:

**Dispatch:** descriptor `DispatchDescriptor(role="engineer")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `---SUBMISSION-CHECKS-START---`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Implement fix task for YOK-{_item_id}: Fix integration simulation gaps (amend cycle)
 {context block}
 Read the authoritative task spec from the DB before starting:
 yoke workflow-item epic-task body-get --epic "{_epic_id}" --task-num "{_fix_task_num}"
 Also read the parent item spec for full context:
 yoke items get YOK-{_item_id} spec
 IMPORTANT: cd to the worktree path FIRST. Commit incrementally. Run tests before finishing.
```

### AF15. Post-Engineer Processing

1. Capture Ouroboros reflections (see `dispatch-context.md` step 5m).
2. Post-Engineer commit sweep (pattern):
 ```bash
 cd {_worktree_path} && git add -A 2>/dev/null
 if ! git diff --cached --quiet 2>/dev/null; then
 _uncommitted_count=$(git diff --cached --name-only | wc -l | tr -d ' ')
 _uncommitted_files=$(git diff --cached --name-only | tr '\n' ', ' | sed 's/,$//')
 git commit -m "chore: auto-commit Engineer uncommitted work [YOK-${_item_id}] (autofix)"
 yoke ouroboros entry insert \
 --agent conduct --category problem --context "YOK-${_item_id}" \
 --observation "Engineer left ${_uncommitted_count} uncommitted file(s) in autofix cycle. Files: ${_uncommitted_files}"
 fi
 ```
3. Record agent ID: `yoke workflow-item epic-task metadata-update --epic "$_epic_id" --task-num "$_fix_task_num" --fields-json '{"agent_id":"ENGINEER_AGENT_ID"}'`
4. Seed review (auto-advances to `reviewing-implementation`): `yoke workflow-item epic-task review-seed --epic "$_epic_id" --task-num "$_fix_task_num"`

### AF16. Merge Main Before Tester

```bash
cd {_worktree_path} && git merge main --no-edit
```

If conflicts: re-dispatch Engineer to resolve. If still unresolved after re-dispatch: Return `AUTOFIX_HALTED`.

### AF17. Dispatch Tester for Fix Task

**Dispatch:** descriptor `DispatchDescriptor(role="tester")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `VERDICT: PASS|FAIL`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Validate fix task for YOK-{_item_id}: Fix integration simulation gaps (amend cycle)
 Repository root: {MAIN_ROOT}
 Read the authoritative task spec:
 yoke workflow-item epic-task body-get --epic "{_epic_id}" --task-num "{_fix_task_num}"
 Engineer's changes (full diff from main): {git diff main...{_worktree_branch}}
 Engineer's changes (this attempt only): {git diff {ATTEMPT_BASELINE_fix}..{_worktree_branch}}
 Regression detection: Compare failing test NAMES between main and the branch.
 Review engineer's work against acceptance criteria. Run tests.
 VERDICT: PASS or VERDICT: FAIL followed by details.
```

### AF18. Process Tester Verdict

1. Capture reflections (see `dispatch-context.md` step 5m).
2. Commit Tester artifacts (see `dispatch-context.md` step 5n).
3. Parse verdict: `yoke workflow-item epic-task review-get --epic "$_epic_id" --task-num "$_fix_task_num"`. Fall back to text search.

**If FAIL:**
- No retry in amend cycle (safety guard).
- ```bash
 yoke conduct epic-task update-status --epic "$_epic_id" --task-num "$_fix_task_num" \
  --status failed --note "Tester failed in autofix amend cycle" \
  --claim-bypass "simulation-autofix:epic-$_epic_id"
 ```
- Print: `Fix task {_fix_task_num} failed testing. Amend cycle halted.`
- Return `AUTOFIX_HALTED`.

**If PASS:**
- The `review_insert` call auto-advanced fix task to `reviewed-implementation`.
- Proceed to AF19.

**If neither found:** Enter the Tester output gate (same pattern as `engineer-tester-closeout.md` Step 9). If no verdict after `MAX_TESTER_REPROMPTS` retries, treat as FAIL and return `AUTOFIX_HALTED`.

### AF19. Final Re-Simulation

```bash
_task_list=$(python3 -m yoke_core.cli.db_router query \
 "SELECT task_num, title, status FROM epic_tasks WHERE epic_id='${_epic_id}' ORDER BY task_num")
```

**Dispatch:** descriptor `DispatchDescriptor(role="simulator")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `SIMULATION: CLEAN|GAPS FOUND`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Run integration simulation for epic {_epic_id} (YOK-{_item_id}).
 Repository root: {MAIN_ROOT}
 All tasks completed testing successfully including auto-created fix task {_fix_task_num}.
 This is the final re-simulation after the amend cycle.
 Trace execution paths across tasks to find any remaining integration gaps.
 IMPORTANT: Your response MUST begin with the two-line verdict block — line 1 is SIMULATION: CLEAN or SIMULATION: GAPS FOUND, line 2 is EPIC: YOK-{_item_id}. Persistence rejects bodies whose attested epic does not match YOK-{_item_id} (exit 16) or that omit the EPIC line entirely (exit 17).
 Worktree-State Authority: a task's resolved worktree checkout is the authority for that task's actual code whether the item/epic has one worktree or many. Main is the base/integration target, not evidence of unmerged task state. Use the task's worktree_path / branch when verifying files; if no worktree path or prompt-supplied diff exists, report evidence missing instead of inspecting main as a substitute.
 Worktree authorities: {_worktree_list from simulation-gate-criteria.md, refreshed}
 Epic tasks: {_task_list}
```

Capture Ouroboros reflections (step 5m pattern).

```bash
set +e
_verified_verdict=$(echo "{simulator_output}" | python3 -m yoke_core.domain.persist_simulation "$_epic_id" "integration")
_persist_rc=$?
set -e
```

- **`_persist_rc` is 0 and `CLEAN`:** Print: `All gaps resolved after Architect fix + amend cycle.` Return `AUTOFIX_CLEAN`.
- **`_persist_rc` is 0 and `GAPS FOUND`:** Print: `Gaps remain after full auto-fix cycle. Manual review required.` Return `AUTOFIX_HALTED`.
- **`_persist_rc` is 16 or 17:** Print the exact epic-identity attestation diagnostic from `persist_simulation` (`wrong-epic body` or `missing-epic body`). Return `AUTOFIX_HALTED` without treating the identity failure as an ordinary gap.
- **`_persist_rc` non-zero:** Print: `Final re-simulation persistence failed (exit code {_persist_rc}). Treating as GAPS FOUND.` Return `AUTOFIX_HALTED`.
