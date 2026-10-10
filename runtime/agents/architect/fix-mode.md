# Architect — Fix Mode

Read when dispatch contains simulation gap report AND **fix mode**. Spec-only
dispatch uses normal planning; no config-triggered switch.

## Inputs

Read original spec/technical_plan structured fields (`yoke items get PREFIX-N
spec` / technical_plan), body if empty; worktree_plan (body/epic directory if
empty); every `epic_tasks.body` via
`yoke workflow-item epic-task body-get --epic {epic-ref} --task-num {task-num}`.
Gap report is supplied inline.

## Process and constraints

Extract each gap number/severity/involved tasks/root cause/fix guidance.
CRITICAL must resolve, WARNING should resolve. NOTE goes in summary only unless
trivial count/typo fix; explicitly record summary-only disposition.

Modify only task specs named by gap guidance: ACs, tests, files and provided/
expected contracts as needed. Preserve all unrelated content exactly. Never
split/merge/reorder/renumber tasks or move worktree assignments. Files changes
update corresponding lane manifest; recheck overlap and flag new cross-lane
collision. Never edit implementation code: summarize **requires `/yoke amend`**.

Epic Technical Plan stays unchanged; epic-wide gap needs **requires manual epic
update**. Sole exception: gap explicitly missing FR Traceability coverage permits
regenerating that section from final corrected task mapping.

## Output (exact order)

### Modified Task Specs

Full content of changed tasks only, each preceded by `### Task 001` etc; no diffs
or unchanged re-output. Parent persists through workflow_item.epic_task.body_replace.

### Modified Worktree Plan

Only if changed: `### Worktree Plan` and full corrected content. Omit otherwise.

### Change Summary

| Gap # | Severity | Artifact Modified | Change Description |
|---|---|---|---|
| {gap} | [CRITICAL]/[WARNING]/[NOTE] | {task/plan or —} | {change/disposition} |

Every gap appears, including summary-only/manual-epic/amend requirements.
