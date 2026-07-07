---
name: usher
description: "Unified merge+deploy command. Takes items from implemented through merge, deployment, and done-transition. Inline orchestration skill -- no subagent spawned."
argument-hint: "YOK-N [YOK-N ...] [--dry-run] [--merge-only] [--deploy-only] [--resume YOK-N]"
---

<!--
 done-transition caller audit: agent-facing execution uses
 python3 -m yoke_core.tools.watch_merge done-transition.
 Raw done_transition engine calls are internal implementation detail.
 Usher is the PRIMARY caller for the implemented -> done path.
 Other valid callers: advance/done/SKILL.md (manual operator transitions).
 EXIT 7 PATTERN: Usher absorbs done-transition exit 7 into its
 post-merge routing logic — never exposes it to operators.
 Full audit details in merge.md.
-->

# /yoke usher YOK-N [YOK-N ...] [--dry-run] [--merge-only] [--deploy-only] [--resume YOK-N]

Unified merge+deploy command. Takes `implemented` items through merge, deployment pipeline, and done-transition.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug not worth a ticket, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Philosophy

**Error/rollback paths are mandatory.** Every merge and deployment operation must have a known recovery path. When a merge fails mid-batch, the pipeline halts with clear state. When a deployment stage fails, the run state is preserved for `--resume`. Never leave items in an ambiguous intermediate state.

**Run state for deployment verification.** Deployment evidence is run state: `deployment_runs.status` / `current_stage` joined through `deployment_run_items` answer "did YOK-N's pipeline succeed" before advancing items past deployment gates. The events ledger is telemetry-only — deployment lifecycle events (`DeploymentRunStageCompleted`, `DeploymentRunFailed`) are audit trail, not verification input.

## Arguments

| Argument | Description |
|----------|-------------|
| `YOK-N [YOK-N ...]` | Explicit items to process (at least one required) |
| `--dry-run` | Show plan without executing |
| `--merge-only` | Merge but do not deploy |
| `--deploy-only` | Deploy already-merged items |
| `--resume YOK-N` | Resume paused deployment (sugar for single-item deploy-only) |

## Phase Dispatch

Before reading the first phase, stamp the session's mode so the board's active-session row reflects the live phase (default `wait` misrepresents an active usher run):

```bash
yoke sessions touch \
 --mode usher
```

Read and follow each phase file in order. Each phase may halt the pipeline (blocked merge, failed deployment, etc.).

**Phase 1 — Collect & Validate:** Read `.agents/skills/yoke/usher/collect.md`
- Parse arguments, collect items, status gate, compute merge order, pre-merge CI check
- Halt recovery when `deploy_stage` shows `<stage>-failed`: see the "Halt recovery: deploy reported failed" sub-section in `collect.md` — runs an internal usher/GitHub reconciliation helper to align Yoke with GH truth before retrying.

**Phase 2 — Plan & Confirm:** Read `.agents/skills/yoke/usher/plan.md`
- Dry run display (if `--dry-run` → stop after), operator confirmation

**Phase 3 — Merge Execution:** Read `.agents/skills/yoke/usher/merge.md`
- Skip if `--deploy-only`
- Pre-merge ephemeral verification, execute merges, handle results, post-merge CI

**Phase 4 — Deployment Routing:** Read `.agents/skills/yoke/usher/deploy.md`
- Skip if `--merge-only`
- Route A (internal flows → done-transition)
- Route B (deployment runs → pipeline execution with inline approval)

**Phase 5 — Finalize:** Read `.agents/skills/yoke/usher/finalize.md`
- Completion report, idempotency rules, pipeline failure recovery, operational notes
