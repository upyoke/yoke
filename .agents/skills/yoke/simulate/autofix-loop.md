# Simulate — auto-fix loop

Shared with Conduct. Without `--auto-fix`, ask before each pass.

- NOTE-only, or no CRITICAL and `PROCEED`: return `AUTOFIX_NOT_REQUIRED`
  (not CLEAN).
- The iteration limit is **3**. Never reset iteration.
- Missing `Fix level:`: `AUTOFIX_HALTED` (`simulation_fix_level_missing`).
- Only code gaps left: `AUTOFIX_CODE_GAPS`.
- Else the Architect fixes task bodies. Only update task bodies it changed,
  via `workflow_item.epic_task.body_replace`. No change:
  `simulation_fix_no_change`. Re-simulate; verified CLEAN: `AUTOFIX_CLEAN`.
- Limit hit with plan gaps: `simulation_fix_iterations_exhausted`.

Never repeat an uncertain write. The caller separately owns its gated
lifecycle transition and claim release.
