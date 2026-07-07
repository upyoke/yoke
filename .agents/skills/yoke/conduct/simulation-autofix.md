# Simulation Auto-Fix Flow

Invoked by `simulation-gate.md` (S6h Branch 3) when the integration simulation returns GAPS FOUND and `--no-auto-fix` is NOT set.

**Inherited from caller:** `SCRIPT_DIR` (must be absolute — resolved by caller after `MAIN_ROOT`), `MAIN_ROOT`, `_epic_id`, `_item_id` (numeric YOK-N number), `_worktree_path`, `_worktree_branch`, `_simulator_output` (raw Simulator output from the initial simulation), `_max_attempts` (for Engineer/Tester dispatch).

**Return values:** `AUTOFIX_CLEAN` (gaps resolved) or `AUTOFIX_HALTED` (gaps remain after exhausting all fix attempts).

**Constants:** `MAX_ARCHITECT_FIX_ITERATIONS=3` (from SKILL.md).

---

## Architect Fix Loop (Plan-Level Fixes)

Bounded to `MAX_ARCHITECT_FIX_ITERATIONS` iterations. Reuses logic from `simulate/SKILL.md` steps 8-12 but with automatic acceptance (no y/n prompts).

**Read and follow: `.agents/skills/yoke/conduct/simulation-autofix-inputs.md`**

This companion file covers AF1–AF3:
- **AF1** — Initialize `_fix_iteration=1`, `_code_level_gaps=""`.
- **AF2** — Check gap severity and recommendation. Return `AUTOFIX_CLEAN` early for NOTE-only gaps or PROCEED+no-CRITICALs anomaly.
- **AF2a** — Pre-route by fix level: if all gaps are code-level, skip Architect and jump directly to Phase 2; if all plan-level, proceed to AF3; if mixed, proceed to AF3 (Architect marks code gaps as "requires /yoke amend").
- **AF3** — Gather context for Architect: read `_sim_report` from DB and all task bodies.

**Read and follow: `.agents/skills/yoke/conduct/simulation-autofix-patching.md`**

This companion file covers AF4–AF9:
- **AF4** — Dispatch Architect in fix mode (`"Fix mode."` trigger phrase).
- **AF5** — Write Architect's fixes to DB (task bodies and worktree plan).
- **AF6** — Track code-level gaps (entries marked "requires /yoke amend").
- **AF7** — Display change summary; capture Ouroboros reflections.
- **AF7a** — Short-circuit to Phase 2 if all gaps are code-level (no plan-level fixes made).
- **AF8** — Re-simulate (dispatch Simulator with updated context).
- **AF9** — Persist and evaluate re-simulation verdict. If CLEAN, return `AUTOFIX_CLEAN`. If GAPS FOUND and iterations remain, loop back to AF2. If iterations exhausted, proceed to Phase 2 if code gaps exist, else return `AUTOFIX_HALTED`.

---

## Amend Cycle (Code-Level Fixes)

Creates a fix task for remaining code-level gaps, dispatches through Engineer/Tester, and re-simulates. Maximum 1 amend cycle.

**Read and follow: `.agents/skills/yoke/conduct/simulation-autofix-verification.md`**

This companion file covers AF10–AF19:
- **AF10** — Parse remaining code-level gaps from DB.
- **AF10a** — Extract dependency task numbers from gap source tasks.
- **AF11** — Create fix task (auto-numbered, task body with ACs per gap).
- **AF12** — Sync fix task to GitHub.
- **AF13** — Append fix task to dispatch chain queue.
- **AF14** — Activate and dispatch Engineer for fix task (YOKE_CLAIM_BYPASS for system-owned task).
- **AF15** — Post-Engineer processing: reflections, commit sweep, agent ID, review seed.
- **AF16** — Merge main before Tester.
- **AF17** — Dispatch Tester for fix task.
- **AF18** — Process Tester verdict: FAIL returns `AUTOFIX_HALTED`; PASS proceeds to AF19.
- **AF19** — Final re-simulation: CLEAN returns `AUTOFIX_CLEAN`; GAPS FOUND or persistence failure returns `AUTOFIX_HALTED`.
