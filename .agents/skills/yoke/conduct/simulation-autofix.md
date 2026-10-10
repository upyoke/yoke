# Conduct — Simulate auto-fix adapter

Read [Simulate](../simulate/SKILL.md) and resume its
[shared auto-fix loop](../simulate/autofix-loop.md) directly with the already
persisted report, --force-integration --auto-fix and caller=conduct/phase=integration.
Retain exact public ref, separately resolved internal id, MAIN_ROOT/project,
registered lane/branch authorities, max attempts and raw report/receipt.
Do not repeat initial simulation or invent a second Architect budget.

Automatic mode accepts plan fixes/re-simulation without operator prompts;
new code remains in Conduct's task pipeline. Every re-simulation uses native
verified simulation-upsert receipt; no local verdict or absent-field fallback.

| Return | Action |
|---|---|
| AUTOFIX_NOT_REQUIRED | Return it with unchanged report/counts/recommendation; no CLEAN or handoff. |
| AUTOFIX_CLEAN | Caller verifies final receipt, parent gates and lifecycle/claim boundary. |
| AUTOFIX_CODE_GAPS | Execute one [amend cycle](simulation-autofix-verification.md); return its CLEAN/HALTED. |
| AUTOFIX_HALTED | Preserve lanes, exact failure/ids/recovery; caller reports HALTED. |

`AUTOFIX_NOT_REQUIRED`: return it to simulation-gate-escalation.md for real
PROCEED triage or unresolved recommendation handling. Restore caller session
mode on return. Only shared Simulate owns Architect dispatch; this adapter never
adds a separate loop, code fix, or synthetic passing record.
