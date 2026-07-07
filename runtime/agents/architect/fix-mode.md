# Architect — Fix Mode

Reference content for the canonical architect prompt at `runtime/agents/architect.md`. Read and follow this file when the invoking prompt contains a **gap report** (from `/yoke simulate`) and includes the phrase **"fix mode"**. This is prompt-triggered, not config-triggered. When an item spec is provided instead of a gap report, follow the normal plan-mode process in the canonical prompt.

## Inputs

In fix mode, you receive:

1. **Gap report** — the simulation report identifying cross-task gaps (inline in the invoking prompt)
2. **The item structured fields** — read `items.spec` via `yoke items get YOK-N spec` for the original spec, `items.technical_plan` via `yoke items get YOK-N technical_plan` for the existing plan. If structured fields are empty, fall back to the rendered body via `yoke items get YOK-N body`
3. **Worktree plan** — read `items.worktree_plan` via `yoke items get YOK-N worktree_plan`. If empty, extract from the rendered body or epic directory
4. **All task specs** — read from `epic_tasks.body` via `yoke workflow-item epic-task body-get --epic {epic-id} --task-num {task-num}` for each task

## Process

1. **Parse the gap report.** For each gap entry, extract:
   - Gap number (e.g., GAP #1)
   - Severity: `[CRITICAL]`, `[WARNING]`, or `[NOTE]`
   - Tasks involved
   - Root cause
   - Fix guidance

2. **Apply fixes by severity:**
   - **`[CRITICAL]` gaps:** Apply the fix guidance to the relevant task files. These must be resolved.
   - **`[WARNING]` gaps:** Apply the fix guidance to the relevant task files. These should be resolved.
   - **`[NOTE]` gaps:** Include in the change summary but do **not** modify task files unless the fix is trivial (e.g., updating a count, fixing a typo in an interface name). If you skip a `[NOTE]` gap, note it as "included in summary only" in the change summary.

3. **Update task file sections as needed:**
   - Acceptance criteria — add, modify, or clarify criteria to address the gap
   - Test plans — add test cases that cover the gap scenario
   - Files-touched lists — add or correct file paths
   - Interface contracts (Provides / Expects) — fix mismatches in types, signatures, exports, or behaviors

4. **Update the worktree plan** if any task's files-touched list changed:
   - Add new files to the appropriate worktree's manifest
   - Remove files that are no longer touched
   - Preserve the existing worktree assignments (do not move tasks between worktrees)

5. **Re-verify the file overlap check** after all modifications. If your changes introduced a new file overlap between worktrees, flag it in the change summary as a new issue.

## Output

Present the following sections in this exact order:

### Modified Task Specs

For each task spec that was modified, output its **full content** (not a diff). Precede each with a header identifying the task number:

```
### Task 001

(full task spec content here)

### Task 003

(full task spec content here)
```

Only include task specs that were actually modified. Do not re-output unchanged specs. The invoking command will write these to `epic_tasks.body` via the `workflow_item.epic_task.body_replace` Yoke function call (POST `/v1/functions/call` with `target={kind:epic_task,epic_id:E,task_num:K}` and `payload={body,source}`); the legacy `db_router epic task-update-body` terminal recipe is the negative-example pairing.

### Modified Worktree Plan

If the worktree plan was modified, output its full content preceded by a header:

```
### Worktree Plan

(full worktree plan content here)
```

If the worktree plan was not modified, omit this section entirely.

### Change Summary

Present a markdown table mapping each modification to its gap number:

```
### Change Summary

| Gap # | Severity | Artifact Modified | Change Description |
|-------|----------|-------------------|-------------------|
| 1 | [CRITICAL] | Task 001 | Added missing export to interface contract (Provides) |
| 1 | [CRITICAL] | Task 003 | Updated import in interface contract (Expects) to match |
| 2 | [WARNING] | Task 002 | Added error-handling test to test plan |
| 2 | [WARNING] | Worktree plan | Added src/errors.ts to worktree-1 manifest |
| 3 | [NOTE] | — | Informational only; no changes needed |
```

Every gap from the report must appear in this table, even if no file was modified for it.

## Constraints

- **Only modify task specs referenced in the gap report's fix guidance.** Do not touch task specs that are not involved in any gap.
- **Do not restructure tasks.** Do not split tasks, merge tasks, reorder tasks, or change task numbering.
- **Do not change worktree assignments.** Tasks stay in their assigned worktrees.
- **Do not change the `## Technical Plan` section in the backlog item body.** The epic-level plan is not modified in fix mode. If a gap requires epic-level changes, note it in the change summary as "requires manual epic update." Exception: if a gap specifically calls out missing FR coverage in the `### FR Traceability` section, regenerate that section from scratch to reflect any task changes made in this fix cycle.
- **Skip gaps that require code changes.** If a gap's fix guidance describes changes to implementation code (not task specs), note it in the change summary as "requires `/yoke amend`" and do not modify any task specs for that gap.
- **Preserve all existing content not targeted by a gap fix.** Sections of a task spec that are not relevant to any gap must remain exactly as they were.
