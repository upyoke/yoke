# Conduct — Integration Simulation Gate (S6h)

Integration simulation stage of the conduct epic flow. Runs after all epic tasks reach `done`, `reviewed-implementation`, `merged`, or `completed`. Dispatches the Simulator to verify cross-task integration before handing off to `/yoke polish`. The result is persisted to `qa_runs` (via `yoke workflow-item epic-task simulation-upsert`) so the polish gate can trust the recorded simulation evidence. **Inherited:** `SCRIPT_DIR`, `MAIN_ROOT`, `_epic_id`, `N`, `_worktree_path`, `_worktree_branch`, `_max_attempts`, `MAX_SIMULATOR_REPROMPTS`, `MAX_ARCHITECT_FIX_ITERATIONS`, `_project`, `_workspace`.

---

#### S6h. Integration Simulation Gate

**Skip check:** If `--force` or `--ignore-gaps` was passed, skip the simulation entirely. Print `Simulation: skipped (--force)`. Do NOT write a simulation record. **Go to `cleanup-report.md`** (6z Board Rebuild, then 7 Final Report) with `SUCCESS`, printing:
```
All tasks in this worktree complete. Run '/yoke polish YOK-{N}' to finish the parent epic.
```

**Read and follow: `.agents/skills/yoke/conduct/simulation-gate-criteria.md`**

This companion file covers the simulation dispatch and result verification:
- **Mode selection** — Standard mode only when `sim_force_standard_integration=true`; compressed two-phase mode is the default.
- **Scope estimation** — Compute task body bytes, review bytes, spec/plan bytes, diff bytes for observability logging only.
- **Standard dispatch** — Full task list, verdict-first requirement.
- **Compressed dispatch** — Interface contracts, file overlap matrix, dependency edges, diff stats; two-phase analysis protocol (Phase A: no-tool preliminary verdict; Phase B: max 5 file reads for verification). Forbidden operations list enforced.
- **Parse local result** — `_local_result` from Simulator output (`CLEAN` or `GAPS FOUND`). If empty, enter the Simulator output gate.
- **Simulator output gate** — Auto-retry up to `MAX_SIMULATOR_REPROMPTS` (2) with escalating strategies: formatting-omission re-prompt (Tier 1), compressed+two-phase+aggressive retry (Tier 2), ultra-compressed no-tool fallback (Tier 3). Gate exhaustion → `HALTED`.
- **Persist and verify** — use the retained internal `persist_simulation` boundary for the integration verdict because it also performs epic-identity attestation and the conduct reviewed-handoff. Non-zero exit → `HALTED`. On success, `_verified_verdict` is set and `_local_result` is updated to match.

**Read and follow: `.agents/skills/yoke/conduct/simulation-gate-escalation.md`**

This companion file covers result branching:
- **CLEAN path** — Satisfy unsatisfied parent item verification requirements; verify auto-handoff to `reviewed-implementation`; print polish invitation; go to `cleanup-report.md` with `SUCCESS`.
- **GAPS FOUND — Branch 1 (PROCEED, no CRITICALs)** — File tickets per gap, satisfy parent verification requirements, call `proceed-triage-handoff`; go to `cleanup-report.md` with `SUCCESS`.
- **GAPS FOUND — Branch 2 (--no-auto-fix)** — Print halt message; go to `cleanup-report.md` with `HALTED`.
- **GAPS FOUND — Branch 3 (CRITICAL gaps or Recommendation ≠ PROCEED)** — Read `simulation-autofix.md`; on `AUTOFIX_CLEAN` verify auto-handoff and go to `cleanup-report.md` with `SUCCESS`; on `AUTOFIX_HALTED` go to `cleanup-report.md` with `HALTED`.

---

**Handoff:** After simulation processing, always read `.agents/skills/yoke/conduct/cleanup-report.md` for board rebuild, main-repo cleanup, and final report.
