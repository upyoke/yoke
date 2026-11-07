# Architect — Fix Mode

Read when the dispatch carries a simulation gap report and **Fix mode.**

## Inputs

The gap report is inline. Read the item's `spec` and `technical_plan`
(`yoke items get PREFIX-N spec technical_plan`), its `worktree_plan`, and each
task body with `yoke workflow-item epic-task body-get --epic PREFIX-N
--task-num {task-num}`.

## Rules

- CRITICAL gaps must be resolved and WARNING gaps should be; a NOTE goes in the
  summary unless it is a trivial count or typo fix.
- Change only the task specs a gap names, and leave everything else in them
  exactly as it was. Never split, merge, reorder or renumber tasks or move
  them between lanes.
- A changed file list updates that lane's worktree plan; recheck overlap and
  flag any new cross-lane collision.
- Never edit implementation code: a code gap is summarized as
  **requires `/yoke amend`**.
- Leave the epic's Technical Plan unchanged; an epic-wide gap is summarized as
  **requires manual epic update**. The one exception: a gap naming missing FR
  Traceability coverage lets you regenerate that table from the corrected
  task mapping.

## Output, in this order

### Modified Task Specs

The full text of each changed task only, each under `### Task 001` and so on;
no diffs and no unchanged tasks.

### Modified Worktree Plan

Only when it changed: `### Worktree Plan` and its full corrected text.

### Change Summary

| Gap # | Severity | Artifact Modified | Change Description |
|---|---|---|---|
| {gap} | [CRITICAL]/[WARNING]/[NOTE] | {task/plan or —} | {change or disposition} |

Every gap appears, including summary-only, manual-epic and amend dispositions.
