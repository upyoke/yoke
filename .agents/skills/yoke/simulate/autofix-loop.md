# Simulate: Shared Architect Auto-Fix Loop

This is the single plan-fix loop for direct Simulate and Conduct's internal
invocation. The Simulator and Architect are read-only; the dispatching skill
writes the returned plan changes through registered item surfaces.

## Entry and caller contract

Retain the epic's internal `_epic_id`, resolved parent `public_ref` and
`item_id`, `phase`, current persisted report and `_simulator_output`, and
registered lane authorities. Never construct a public ref from an internal id.
Direct invocation has `caller=simulate`. Conduct supplies `caller=conduct`,
`phase=integration`, an already persisted initial report, and its task-pipeline
context; start here without repeating the initial simulation.

`--auto-fix` means automatic acceptance of plan fixes and re-simulation.
Without it, prompt `Auto-fix? The Architect will apply the report's fix guidance
to the task specs. (y/n)` and stop if declined. For integration, explain that
code fixes require an amend cycle; direct Simulate does not execute them.
Only `[CRITICAL]` or `[WARNING]` gaps enter the loop. Notes alone need no fixes.

The Architect iteration limit is **3**, owned here. Initialize
`iteration=1` and `_code_level_gaps` empty. Never reset iteration when returning
to severity/context gathering after a re-simulation.

## Classify and gather

On each iteration, parse the current report's severity, fix guidance, and
`Fix level:` fields. Extract code gaps with their gap number, title, severity,
root cause, affected tasks/files, and fix guidance into `_code_level_gaps`.

- All fixable gaps are code-level: skip the Architect and return
  `AUTOFIX_CODE_GAPS` with that context.
- Plan or mixed gaps remain: gather their context for the Architect.
- A missing fix-level classification is a named `simulation_fix_level_missing`
  refusal. Return `AUTOFIX_HALTED`; recovery is a corrected Simulator report
  classifying each fixable gap as plan, code, or mixed. Do not silently guess.

Read the current report with:

```text
yoke workflow-item epic-task simulation-get --epic <epic-id> --phase <phase>
```

Read all tasks from `yoke epic-tasks list --epic <epic-id>` and each body with
`yoke workflow-item epic-task body-get --epic <epic-id> --task-num <task-num>`.
Include the parent spec and worktree plan plus the current report in context.

## Dispatch Architect in fix mode

Use `DispatchDescriptor(role="architect")`, rendered through
`yoke_core.domain.dispatch_descriptors.render_for_harness` for the active
harness. Fill its prompt with:

```text
Fix mode.
Item: {public_ref}
Repository root: {main_root}

## Gap Report
{current persisted report}

Read the authoritative parent spec:
yoke items get {public_ref} spec

## Task Content
{each task's number, title and complete body, headed ### Task NNN}

## Instructions
Apply the report's fix guidance to affected task specs and the worktree plan.
Only modify tasks referenced in that guidance.
Return full modified task bodies headed ### Task NNN, a modified Worktree Plan
when needed, and a change summary table:
Gap # | Severity | Task Modified | Change Description
Skip code changes; mark those entries "requires /yoke amend".
```

Capture reflections through the harness's existing reflection contract.
Show the change summary, and add its code-only entries to `_code_level_gaps`.

## Persist plan fixes

Only update task bodies named as actually modified in the change summary.
Call `workflow_item.epic_task.body_replace` with target
`{kind: "epic_task", epic_id: <internal-id>, task_num: <task-number>}` and
payload `{body: <full-modified-body>}`.

For a changed worktree plan, call `items.structured_field.replace` with target
`{kind: "item", item_id: <internal-id>}` and payload
`{field: "worktree_plan", content: <full-plan>, source: "simulate"}`.
See [the structured write envelopes](../idea/body-and-sync-functions.md).
Do not update a task merely because its body was echoed in the response.
Any failed write returns `AUTOFIX_HALTED` with its refusal and recovery.

If no plan changes were made, return `AUTOFIX_CODE_GAPS` when code gaps exist.
Otherwise return `AUTOFIX_HALTED` with `simulation_fix_no_change`: the Architect
produced no applicable fix; recovery is to correct the gap guidance or plan.

## Re-simulate and evaluate

Without `--auto-fix`, ask `Re-simulate to verify fixes? (y/n)` and stop if
declined. Automatic mode proceeds immediately.

Run [epic-flow.md](epic-flow.md) steps 3–7 for the retained phase, refreshing
all task bodies, reviews, contracts, lane authorities and diffs. Use its
canonical Simulator prompts and compressed/standard selection; do not invoke
this auto-fix phase recursively. Conduct context uses the retained
`persist_simulation` boundary in epic-flow's persistence step, so the verdict
is identity-attested and the reviewed-handoff occurs on CLEAN.

- A successfully persisted `CLEAN` returns `AUTOFIX_CLEAN`; show the iteration
  count. Never infer success from an unpersisted local verdict.
- An absent verdict, persistence failure, wrong-epic body (exit 16), or
  missing-epic body (exit 17) returns `AUTOFIX_HALTED`, preserving the exact
  diagnostic. Recovery is to correct the report identity/format or the named
  persistence failure, then re-run the simulation. It is not another plan gap.
- `GAPS FOUND`: replace `_simulator_output` and the retained report with the
  newly persisted report. Reclassify remaining gaps; return
  `AUTOFIX_CODE_GAPS` immediately when all remaining fixable gaps are code-level.
- If plan gaps remain and `iteration < 3`, increment iteration and return to
  classification/context gathering. Interactive mode asks before each pass;
  automatic mode proceeds without prompts.
- At the limit, return `AUTOFIX_CODE_GAPS` when code gaps remain (including any
  unresolved plan gaps for final verification), otherwise `AUTOFIX_HALTED` with
  `simulation_fix_iterations_exhausted`. Surface the remaining report and
  recovery: correct its unresolved guidance manually and re-simulate.

## Return to the caller

Direct Simulate displays remaining code gaps with amend guidance and stops;
it never reports them as clean. Conduct consumes `AUTOFIX_CODE_GAPS` through
its single Engineer/Tester amend cycle, then checks final simulation and the
reviewed-handoff. `AUTOFIX_HALTED` preserves all work and the named recovery.
An internal invocation restores the caller's session mode before returning.
