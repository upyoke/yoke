# Simulate Phase: Architect Auto-Fix Loop

This phase owns the optional Architect-assisted fix cycle after a simulation report contains fixable `[CRITICAL]` or `[WARNING]` gaps.

## 8. Offer Auto-Fix

After displaying the simulation summary, check whether the report contains fixable gaps.

- If the report contains `[CRITICAL]` or `[WARNING]`, prompt:
 ```text
 Auto-fix? The Architect will apply the gap report's fix guidance to the task specs. (y/n)
 ```
- For integration-phase simulations, append:
 ```text
 Note: Code-level gaps will be skipped — only plan-level fixes will be applied. Code fixes require `/yoke amend`.
 ```
- If only `[NOTE]` gaps or no gaps exist, skip auto-fix entirely.

If the operator declines, stop. Otherwise initialize `iteration=1`.

## 9. Invoke The `yoke-architect` Subagent In Fix Mode

Display:

```text
Fix iteration {iteration}/3
```

Read the gap report from DB:

```bash
python3 -m yoke_core.cli.db_router epic simulation-get "{epic-id}" "{phase}"
```

Use this prompt:

```text
Fix mode.
Item ID: YOK-{item_id}

## Gap Report
{contents of simulation report}

Read the authoritative item spec from the DB:
yoke items get YOK-{item_id} spec

## Task Content
{for each task: task number, title, and body content}

## Instructions
Apply the fix guidance from the gap report to the affected tasks and worktree plan.
Produce: modified task content (full content, each preceded by `### Task NNN`), modified Worktree Plan section if applicable, and a change summary table with columns: Gap #, Severity, Task Modified, Change Description.
Only modify tasks referenced in the gap report's fix guidance.
Skip gaps requiring code changes (note as `requires /yoke amend` in the change summary).
```

The trigger phrase `Fix mode.` activates the Architect's fix-mode behavior.

## 10. Write Fixes To DB

Parse the Architect output for task headers such as `### Task 001` and extract the content following each header.

Parse the change summary table to determine which tasks were actually modified. Only update tasks that appear in the change summary.

Write each modified task body back to the DB via the
`workflow_item.epic_task.body_replace` function call (envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)):
`target = {kind: "epic_task", epic_id: <epic-id>, task_num:
<task_num>}`, `payload = {body: "<modified task body content>"}`.

If the Worktree Plan changed, dispatch `items.structured_field.replace`
on the parent epic with `target = {kind: "item", item_id: <epic-id>}`
and `payload = {field: "worktree_plan", content: "<updated worktree
plan>", source: "simulate"}`.

## 11. Display The Change Summary

Show the Architect's change summary table to the operator. It should include:
- Gap number
- Severity
- File or task modified
- Change description

## 12. Re-Simulation Loop

Prompt:

```text
Re-simulate to verify fixes? (y/n)
```

- If the operator declines, stop.
- If the operator accepts, re-run the epic simulation flow.

After re-simulation:
- If the result is clean, report:
 ```text
 All gaps resolved after {iteration} fix iteration(s). Safe to proceed.
 ```
- If gaps remain and `iteration < 3`, increment `iteration` and return to step 8
- If gaps remain and `iteration == 3`, stop and report the remaining gaps with guidance to resolve them manually or via `/yoke amend`
