# Conduct Simulation Auto-Fix Adapter

Invoked by `simulation-gate.md` Branch 3 when auto-fix is enabled.
Conduct delegates the Architect loop to Simulate; this file only connects its
result to Conduct's code-fix task execution and reviewed-handoff checks.

## Invoke Simulate internally

Read and invoke [Simulate](../simulate/SKILL.md) with the epic's internal id,
`--force-integration --auto-fix`, and this retained caller context:
- `MAIN_ROOT`, `_epic_id`, the resolved parent public ref and internal item id
- `_worktree_path`, `_worktree_branch`, `_max_attempts`
- `_simulator_output` and the already persisted integration report
- `caller=conduct`, `phase=integration`

Resume directly at [Simulate's shared auto-fix loop](../simulate/autofix-loop.md)
using the existing report; do not repeat the initial simulation. Automatic mode
accepts plan fixes and re-simulation without operator prompts. Simulate returns
`AUTOFIX_NOT_REQUIRED` with the unchanged report, counts and recommendation,
`AUTOFIX_CLEAN`, `AUTOFIX_CODE_GAPS` with `_code_level_gaps`, or
`AUTOFIX_HALTED` with the named failure and recovery.

## Map the result

- `AUTOFIX_NOT_REQUIRED`: return it with the retained report to
  `simulation-gate-escalation.md`; no CLEAN verdict or auto-handoff occurred.
- `AUTOFIX_CLEAN`: return it to `simulation-gate-escalation.md`, which checks
  the authoritative reviewed-handoff and claim release.
- `AUTOFIX_CODE_GAPS`: read `simulation-autofix-verification.md` and execute
  its single amend cycle, including Engineer/Tester gates and final persisted
  re-simulation. Return that cycle's `AUTOFIX_CLEAN` or `AUTOFIX_HALTED`.
- `AUTOFIX_HALTED`: preserve the lane and return the exact diagnostic to
  `simulation-gate-escalation.md` and `cleanup-report.md`.

Restore the caller's session mode on return. No second Architect loop lives
in Conduct, and code-fix execution remains owned by its task pipeline.
