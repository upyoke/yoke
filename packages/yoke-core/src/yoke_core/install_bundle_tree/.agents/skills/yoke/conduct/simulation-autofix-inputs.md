# Simulation Auto-Fix — Inputs Protocol (AF1–AF3)

Invoked from `simulation-autofix.md` Phase 1 start. Covers initialization, gap severity classification, pre-routing by fix level, and context gathering for the Architect.

**Inherited:** `MAIN_ROOT`, `_epic_id`, `_item_id`, `_worktree_path`, `_worktree_branch`, `_simulator_output`, `_max_attempts`, `MAX_ARCHITECT_FIX_ITERATIONS`.

**Constants:** `MAX_ARCHITECT_FIX_ITERATIONS=3`.

---

### AF1. Initialize

```
_fix_iteration=1
_code_level_gaps=""
```

### AF2. Check Gap Severity and Recommendation

Parse `_simulator_output`:
```bash
_critical_count=$(echo "$_simulator_output" | grep -c '\[CRITICAL\]' || true)
_warning_count=$(echo "$_simulator_output" | grep -c '\[WARNING\]' || true)
_recommendation=$(echo "$_simulator_output" | grep '^- Recommendation:' | sed 's/.*Recommendation: //')
```

If `_critical_count = 0` AND `_warning_count = 0`:
- Only `[NOTE]` gaps remain. Print: `Simulation gaps are NOTE-only. No auto-fix needed.`
- Return `AUTOFIX_CLEAN`.

If `_critical_count = 0` AND `_recommendation = "PROCEED"`:
- Safety net: caller should have handled this. Print: `WARNING: Autofix invoked with PROCEED recommendation and no CRITICALs. This should have been handled by the ticket-filing path in the caller. Returning AUTOFIX_CLEAN.`
- Return `AUTOFIX_CLEAN`.

### AF2a. Pre-Route by Fix Level

Parse `_simulator_output` for `Fix level:` on each `[WARNING]` or `[CRITICAL]` gap:

```
_plan_gaps = count of CRITICAL/WARNING gaps with fix_level "plan" or "mixed"
_code_gaps = count of CRITICAL/WARNING gaps with fix_level "code"
_has_fix_level = whether ANY gap contains a "Fix level:" field
```

**If `_has_fix_level` is false (backward compatibility):**
- Fall through to AF3 (always dispatch Architect first).

**If `_plan_gaps == 0` AND `_code_gaps > 0` (all code-level):**
- Print: `All {_code_gaps} gap(s) are code-level. Skipping Architect (Phase 1) and proceeding directly to amend cycle.`
- Populate `_code_level_gaps` from gap report: extract gap numbers, titles, severity, root cause, and fix guidance for all CRITICAL/WARNING gaps with `fix_level: code`.
- Jump directly to **Phase 2** (`simulation-autofix-verification.md` AF10).

**If `_code_gaps == 0` (all plan-level or mixed):**
- Proceed to AF3 (normal Architect flow).

**If both `_plan_gaps > 0` AND `_code_gaps > 0` (mixed):**
- Proceed to AF3 (Architect handles plan/mixed gaps, marks code gaps as "requires /yoke amend").
- After Architect returns, AF7a short-circuit handles remaining code gaps.

### AF3. Gather Context for Architect

Read the gap report from DB:
```bash
_sim_report=$(yoke workflow-item epic-task simulation-get --epic "$_epic_id" --phase integration)
```

Read all task bodies for the epic:
```bash
_task_rows=$(yoke db read --format lines "SELECT task_num, title FROM epic_tasks WHERE epic_id='${_epic_id}' ORDER BY task_num")
```

For each task:
```bash
yoke workflow-item epic-task body-get --epic "$_epic_id" --task-num "{task_num}"
```

Assemble task content block with `### Task {NNN}` headers.

---

**Handoff:** Context gathered. Read and follow `.agents/skills/yoke/conduct/simulation-autofix-patching.md` to continue with AF4 (Architect dispatch in fix mode).
