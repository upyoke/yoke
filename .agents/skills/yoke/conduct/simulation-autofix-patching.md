# Simulation Auto-Fix — Patching Protocol (AF4–AF9)

Invoked from `simulation-autofix-inputs.md` AF3 handoff. Covers Architect dispatch in fix mode, writing fixes to DB, tracking code-level gaps, change summary display, short-circuit logic, and re-simulation with verdict evaluation.

**Inherited:** `SCRIPT_DIR`, `MAIN_ROOT`, `_epic_id`, `_item_id`, `_worktree_path`, `_worktree_branch`, `_simulator_output`, `_max_attempts`, `MAX_ARCHITECT_FIX_ITERATIONS`, `_fix_iteration`, `_code_level_gaps`, `_sim_report`, task content block.

---

### AF4. Dispatch Architect in Fix Mode

Print: `Auto-fix iteration {_fix_iteration}/{MAX_ARCHITECT_FIX_ITERATIONS} for {_epic_id}`

**Dispatch:** descriptor `DispatchDescriptor(role="architect")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Fix mode.
 Item ID: YOK-{_item_id}
 Repository root: {MAIN_ROOT}

 ## Gap Report
 {contents of simulation report body from _sim_report}

 Read the authoritative item spec from the DB (do not rely on any inline content):
 yoke items get YOK-{_item_id} spec

 ## Task Content
 {for each task:
 ### Task {NNN}
 {body from yoke workflow-item epic-task body-get}
 }

 ## Instructions
 Apply the fix guidance from the gap report to the affected tasks and worktree plan.
 Produce: modified task content (full content, each preceded by ### Task NNN header),
 modified Worktree Plan section (if applicable), and a change summary table
 (columns: Gap #, Severity, Task Modified, Change Description).
 Only modify tasks referenced in the gap report's fix guidance.
 Skip gaps requiring code changes (note as "requires /yoke amend" in the change summary).
```

The trigger phrase `"Fix mode."` activates the Architect's fix behavior.

### AF5. Write Fixes to DB

Parse the Architect's output for task headers (`### Task 001`) and extract content after each header.

Parse the change summary table: **only update tasks that appear in the change summary table.**

Dispatch the `workflow_item.epic_task.body_replace` function call
(envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md))
with `target = {kind: "epic_task", epic_id: "$_epic_id", task_num:
<task_num>}` and `payload = {body: "<modified task body content>"}`.

If the Worktree Plan was modified, dispatch
`items.structured_field.replace` on the parent epic with `target =
{kind: "item", item_id: "${_item_id}"}` and `payload = {field:
"worktree_plan", content: "<modified worktree plan>", source:
"conduct"}`.

### AF6. Track Code-Level Gaps

Parse the Architect's change summary for entries marked `"requires /yoke amend"`. Accumulate into `_code_level_gaps` (gap numbers, summaries, fix guidance).

### AF7. Display Change Summary

Show the Architect's change summary table. Example:
```
| Gap # | Severity | Task Modified | Change Description |
|-------|----------|---------------|--------------------|
| 2 | WARNING | Task 003 | Added missing AC for... |
| 3 | WARNING | Worktree Plan | Updated file list to... |
| 4 | NOTE | — | requires /yoke amend |
```

Capture Ouroboros reflections (see `dispatch-context.md` step 5m pattern).

### AF7a. Short-Circuit to Phase 2 When All Gaps Are Code-Level

Parse the change summary: count actual modifications vs entries marked `"requires /yoke amend"`.

```
_plan_fixes_count = rows with actual modifications
_code_only_count = rows marked "requires /yoke amend"
```

**If `_plan_fixes_count == 0` (no plan-level fixes):**
- Print: `All {_code_only_count} gap(s) require code changes. Architect cannot resolve at plan level. Skipping re-simulation and proceeding to amend cycle.`
- Skip AF8 and AF9.
- If `_code_level_gaps` non-empty: proceed directly to **Phase 2** (`simulation-autofix-verification.md` AF10).
- If `_code_level_gaps` empty (safety): Return `AUTOFIX_HALTED`.

**If `_plan_fixes_count > 0`:**
- Proceed to AF8.

### AF8. Re-Simulate

**Dispatch:** descriptor `DispatchDescriptor(role="simulator")` rendered via `yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`. Result-schema markers: `SIMULATION: CLEAN|GAPS FOUND`, `---REFLECTION-START---`. The descriptor's `prompt: |` block is filled with:
```
 Run integration simulation for epic {_epic_id} (YOK-{_item_id}).
 Repository root: {MAIN_ROOT}
 Scripts directory: {MAIN_ROOT}/.agents/skills/yoke/scripts
 All tasks completed testing successfully. Re-simulating after Architect fix iteration {_fix_iteration}.
 Trace execution paths across tasks to find remaining cross-task integration gaps.
 IMPORTANT: Your response MUST begin with the two-line verdict block — line 1 is SIMULATION: CLEAN or SIMULATION: GAPS FOUND, line 2 is EPIC: YOK-{_item_id}. Persistence rejects bodies whose attested epic does not match YOK-{_item_id} (exit 16) or that omit the EPIC line entirely (exit 17).
 Worktree-State Authority: a task's resolved worktree checkout is the authority for that task's actual code whether the item/epic has one worktree or many. Main is the base/integration target, not evidence of unmerged task state. Use the task's worktree_path / branch when verifying files; if no worktree path or prompt-supplied diff exists, report evidence missing instead of inspecting main as a substitute.
 Worktree authorities: {_worktree_list from simulation-gate-criteria.md, refreshed}

 Epic tasks:
 {_task_list from AF3, refreshed}
```

Capture Ouroboros reflections (step 5m pattern).

### AF9. Persist and Evaluate Re-Simulation

```bash
set +e
_verified_verdict=$(echo "{simulator_output}" | python3 -m yoke_core.domain.persist_simulation "$_epic_id" "integration")
_persist_rc=$?
set -e
```

**If `_persist_rc` is 14 (no local verdict parseable):**
- Treat as `GAPS FOUND`. Log: `Re-simulation returned no parseable result. Treating as GAPS FOUND (safe default). [Simulator output gate — autofix]`
- Log Ouroboros entry. Continue to GAPS FOUND handling below.

**If `_persist_rc` is 16 or 17 (epic-identity attestation failure):**
- Return `AUTOFIX_HALTED`. Log the exact persist diagnostic (`wrong-epic body` for exit 16, `missing-epic body` for exit 17) and surface it through `cleanup-report.md` rather than treating it as a simulation gap. Wrong-epic and missing-epic bodies are identity failures, not architectural gaps.

**If `_persist_rc` non-zero and not 14, 16, or 17 (persistence failure):**
- Treat as `GAPS FOUND`. Log: `Persistence helper failed (exit code {_persist_rc}). Treating as GAPS FOUND.`
- Log Ouroboros entry. Continue to GAPS FOUND handling below.

**If `_persist_rc` is 0 and `_verified_verdict` is `CLEAN`:**
- Print: `All gaps resolved after {_fix_iteration} Architect fix iteration(s).`
- Return `AUTOFIX_CLEAN`.

**If GAPS FOUND and `_fix_iteration < MAX_ARCHITECT_FIX_ITERATIONS`:**
- Update `_simulator_output` with new Simulator output.
- Check whether remaining gaps are all code-level (compare re-simulation gaps against `_code_level_gaps`). If all remaining CRITICAL/WARNING gaps match:
 - Print: `Remaining gaps are all code-level. Skipping further Architect iterations and proceeding to amend cycle.`
 - If `_code_level_gaps` non-empty: proceed to **Phase 2** (`simulation-autofix-verification.md` AF10).
- Otherwise: increment `_fix_iteration` and **go to AF2** (loop — re-read inputs file for AF2/AF2a/AF3 if needed, then return here for AF4).

**If GAPS FOUND and `_fix_iteration >= MAX_ARCHITECT_FIX_ITERATIONS`:**
- Print: `Architect fix loop exhausted ({MAX_ARCHITECT_FIX_ITERATIONS} iterations). Remaining gaps: {count}`
- If `_code_level_gaps` non-empty: proceed to **Phase 2** (`simulation-autofix-verification.md` AF10).
- If `_code_level_gaps` empty: Return `AUTOFIX_HALTED`.

---

**Handoff:** When code-level gaps remain after exhausting Architect iterations or short-circuiting, read and follow `.agents/skills/yoke/conduct/simulation-autofix-verification.md` for the amend cycle (AF10 onward).
