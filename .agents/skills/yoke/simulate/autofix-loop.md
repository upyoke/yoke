# Simulate — auto-fix loop

Shared with Conduct. Without `--auto-fix`, ask before each pass.

- NOTE-only, or no CRITICAL and `PROCEED`: return `AUTOFIX_NOT_REQUIRED`
  (not CLEAN).
- The iteration limit is **3**. Never reset iteration.
- Missing `Fix level:`: `AUTOFIX_HALTED` (`simulation_fix_level_missing`).
- Only code gaps left: `AUTOFIX_CODE_GAPS`.
- Else dispatch yoke-architect with `Fix mode.`, the ref, the report and
  every task body. Write back only what it changed (no change:
  `simulation_fix_no_change`):
  ```text
  yoke workflow-item epic-task body-replace --epic PREFIX-N --task-num N --stdin
  yoke items structured-field replace PREFIX-N --field worktree_plan --source simulate --stdin
  ```
  Re-simulate; verified CLEAN: `AUTOFIX_CLEAN`.
- Limit hit with plan gaps: `simulation_fix_iterations_exhausted`.

Never repeat an uncertain write. The caller separately owns its gated
lifecycle transition and claim release.
