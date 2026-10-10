# Simulate — epic flow

## Resolve phase and context

Read the complete public ref and pinned definition. No tasks means
task_graph_missing: restore the graph through that definition's authoring
binding and [shared handoff recipe](../shared/stage-handoff.md), then retry.

```text
yoke epic-tasks list --epic {epic-ref} --json
yoke items detail get {epic-ref} --json
```

All planning/planned → plan; all completed/merged → integration. Otherwise
report actual states and wait. --force-integration permits integration only
with explicit incomplete-task exclusions in the prompt and resulting report.

Gather full parent spec, technical/worktree plans and every task body.
Integration also needs statuses, reviews and registered task/chain lane,
branch and worktree_path. Actual task lanes are code authority in one lane or
many; main is the base/merge target. Missing lane/diff is missing evidence.

```text
yoke items get {epic-ref} spec
yoke items get {epic-ref} technical_plan
yoke items get {epic-ref} worktree_plan
yoke workflow-item epic-task body-get --epic {epic-ref} --task-num {task_num}
yoke workflow-item epic-task review-get --epic {epic-ref} --task-num {task_num}
```

Integration defaults to compressed unless sim_force_standard_integration=true.
Log scope bytes for bodies/reviews/spec/plans/diff stats plus configured
preflight thresholds; these are observations, not a mode-selection gate.

```text
_force_standard=$(python3 -m yoke_core.domain.runtime_settings get sim_force_standard_integration false)
_pflight_tasks=$(python3 -m yoke_core.domain.runtime_settings get sim_preflight_task_threshold 8)
_pflight_kb=$(python3 -m yoke_core.domain.runtime_settings get sim_preflight_size_kb 20)
```

Compressed bundle: task interfaces, explicit shim exports, lane authorities,
file overlaps, dependency edges, change summaries, branch diff stats, reviews
and parent-supplied commit-boundary evidence. Standard adds full diffs from
each actual task branch. Follow [dispatch-prompts.md](dispatch-prompts.md):
dispatch its common contract plus exactly the matching mode. Capture
reflections through the active harness contract; do not duplicate automatic
hook capture. Manual recovery/backfill first verifies capture was absent.

## Persist once and verify

Every initial/retry report starts with SIMULATION: CLEAN or GAPS FOUND, then
EPIC: {epic-ref}. Both direct and Conduct callers use the registered surface:

```text
yoke workflow-item epic-task simulation-upsert --epic {epic-ref} --phase {phase} --stdin --json < {REPORT_FILE}
```

Capture the original write receipt. Require matching public_ref, phase and
verdict, verified=true and positive requirement_id/run_id. Verification is
for that exact receipt's run; an absent field, local verdict or another latest
run cannot substitute. Persist CLEAN too. Any refusal stops with exact code/
message, requested/attested refs and returned ids; preserve evidence and named
recovery. Do not repeat an uncertain write or use source-private persistence.
This receipt does not advance lifecycle or release Conduct's work claim.
Conduct separately completes native parent QA and its pinned gated handoff.

## Summary and continuation

Display phase, actual CRITICAL/WARNING/NOTE counts, recommendation and receipt.
Critical gaps require resolution; warnings need acceptance or fixes. Claim
clean only from the verified CLEAN receipt. Read the stored report with:

```text
yoke workflow-item epic-task simulation-get --epic {epic-ref} --phase {phase}
```

Approved fixes or --auto-fix continue [autofix-loop.md](autofix-loop.md).
A re-simulation returns its verified report/verdict to the existing iteration;
never starts another loop or resets its budget.
