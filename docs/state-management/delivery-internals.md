# Delivery Lifecycle Internals

Detail pages for the deployment-run pipeline used when an item's pinned
workflow version binds the `usher` skill and declares
`policies.delivery=release_stage`. The high-level handoff lives in
[state-management.md](../state-management.md#delivery-lifecycle); this file
covers the run mechanics, halt states, deployment step runner types, and
ephemeral environments referenced from there.

## Deployment Runs

Stage authority now lives on the `deployment_runs` row (`current_stage`
column), not on individual items. A deployment run groups one or more items
into a single pipeline execution for delivery.

**Run statuses:** `created → executing → succeeded | failed | cancelled`

**Member-item lifecycle during a run:** The current `release_stage`
definitions use `implemented`, `release`, and `done` for their Usher binding.
Those names are definition-owned, not a universal item progression.

- Items remain at `implemented` while the run is `created` (queued but not executing)
- Items transition to `release` when the run starts `executing`
- Items transition to `done` when the run `succeeded` and all blocking `post_deploy` and `manual_acceptance` QA is satisfied

**The `deploy_stage` column** on the `items` table is retained as a read cache during the transition period, kept in sync with the run's `current_stage`. New code should read stage from the run, not from the item. See `packages/yoke-core/src/yoke_core/domain/approval.py` constants `STAGE_AUTHORITY_FIELD` (`current_stage`) and `STAGE_CACHE_FIELD` (`deploy_stage`) for the canonical machine-readable distinction.

## Halt States

> **Vocabulary note:** Halt states (`awaiting-approval`,
> `needs-capability`) are **run-level conditions**, not item lifecycle
> statuses. Members of the current `release_stage` workflows remain at their
> definition's `release` stage while halted. The halt-state registry is
> `yoke_core.domain.approval`; item stage, gate, and policy authority comes
> from the pinned version interpreted by `yoke_core.domain.workflow_runtime`.

Two conditions act as halt states during deployment run execution (items at these halt states remain at `status=release`):

**`needs-capability`** — A step runner detected a missing or misconfigured project capability (exit code 2). The run is blocked until the operator configures the capability in `project_capabilities` and re-runs `/yoke usher YOK-N`. The Usher does not attempt to proceed or guess — it exits cleanly.

**Human approval gate** — When the pipeline encounters a stage with `step_runner: "human-approval"`, the run halts at that stage. The item is blocked until the operator runs `/yoke approve YOK-N [--note "..."]`, which advances the run's `current_stage` to the next stage in the flow. The operator then re-runs `/yoke usher YOK-N` to resume.

**External projects:** When a project-owned `github-actions-workflow` stage
targets a protected GitHub environment, GitHub's native protection rules pause
the Actions run. The Usher records the wait on the deployment run; approval
happens in GitHub, not through `/yoke approve`. Once protection is satisfied,
the Usher's next poll sees the workflow resume and advances the declared stage.
The flow's stored stages own the stage chain and workflow filenames.

Both halt states are visible on the board. Items at `release` with halted runs are not counted as WIP.

## Capability Self-Invention

When a step runner encounters a missing capability, it follows the capability self-invention protocol:

1. The step runner exits with code 2 and writes capability details to stdout (`CAPABILITY_NEEDED`, `REASON`, `TEMPLATE`)
2. Usher records the capability need as an event via `yoke_core.domain.events.emit_event`
3. If the template is novel (`TEMPLATE = 'NEW'`), Usher saves it to `capability_templates`
4. Usher halts the deployment run and exits (items stay at `release`)
5. Operator configures the capability (adds row to `project_capabilities`) and re-runs `/yoke usher YOK-N`

## Human Approval Gate

When the pipeline encounters a `human-approval` step runner stage:

1. Pipeline halts the deployment run at the approval stage and exits with code 2
2. Items remain at `status = 'release'` with the run halted
3. Operator reviews and runs `/yoke approve YOK-N [--note "..."]`
4. Approve advances the run's `current_stage` to the next stage in the flow
5. Operator re-runs `/yoke usher YOK-N` to continue from that next stage

## Step Runner Dispatch

The Python pipeline owner is `yoke_core.domain.deploy_pipeline`. The pipeline dispatches each stage by `step_runner` (or by `kind` for governed migration stages). Known current types:

| Stage shape | Step runner/kind | Description | Exit codes |
|-----------------|--------|-------------|------------|
| step runner | `auto` | No-op stage (`merged`, `complete`) | 0 (always) |
| kind | `migration_apply` | Verifies governed migration evidence for member items; item-less runs pass with explicit run-stage evidence | 0=pass, 1=failure |
| step runner | `environment-activate` | Ensures the target environment host is running and reachable | 0=ready, 1=failure |
| step runner | `core-container-deploy` | Builds/pushes/reuses the pinned Yoke core image and converges the target host | 0=deployed, 1=failure |
| step runner | `health-check` | HTTP GET; Yoke core env checks require x-request-id echo | 0=healthy, 1=failure |
| step runner | `warm-up` | One heavy relayed function call so the pipeline pays the rolled box's cold start | 0=warm, 1=failure |
| step runner | `ephemeral-deploy` / `ephemeral-teardown` / `ephemeral-verify` | Manages preview environments | 0=pass, 1=failure |
| step runner | `human-approval` | Halts pipeline for human approval | Pipeline exits 2 |
| step runner | `github-actions-workflow` | Triggers and polls GitHub Actions workflow | 0=success, 1=failed |

**`github-actions-workflow`:** Used for external projects where deployment is managed by GitHub Actions. The Python deploy pipeline resolves repository authority from DB/project capabilities, triggers or finds the configured workflow run, stores the workflow run id in deployment telemetry, and polls until the workflow reaches a terminal state. GitHub Actions run states map as follows:

- `queued` / `waiting` → poll returns exit 2, pipeline continues polling
- `in_progress` → poll returns exit 3, pipeline continues polling
- `completed` + `success` → poll returns exit 0, pipeline advances to next stage
- `completed` + `failure` → poll returns exit 1, `deploy_stage = '{stage-name}-failed'`, halt

**Yoke core health-check:** Env-resolved Yoke core health checks prove three things before the release is healthy: public `/v1/health` responds, the response echoes the request id, and the response `build` matches the image tag the pipeline deployed. After that passes, the health stage fetches the target HTTPS env's `/v1/cli/manifest` and compares it to this checkout's local CLI manifest. A release fails if the deployed API is missing a local wrapped subcommand such as `strategy.doc.create`; the fix is to deploy/update the Yoke API, not to bypass the HTTPS path.

**Warm-up:** A rolled box answers its health probe long before it can answer
real work — the first heavy relayed call pays the whole server cold start
(engine imports, connection pool, caches) and can outlast the client's relay
ceiling, failing at the caller while the box is healthy and warm steady-state
latency is a second or two. The `warm-up` stage makes that first call from the
pipeline, over the same HTTPS relay a client uses, against the
`connection_env` the stage names. It defaults to `board.data.get` with a 180s
timeout, records the call and its measured latency on the run as
`DeploymentRunWarmedUp`, and fails the stage with the real error rather than
letting a run report success over a cold box.

## Current `release_stage` Usher State Machine

```
Entry: the pinned definition's active skill is `usher`
       and its current built-in handoff stage is `implemented`

1. Create deployment_run (status = 'created')
2. Enroll items via deployment_run_items for item-bound delivery; skip for environment-level deploys
3. Materialize run-level QA requirements
4. Set run status = 'executing'; set member items to `release` only when member items exist

For each stage in deployment_flow.stages:
 1. Set run.current_stage = stage.name
 2. Emit DeploymentRunStageStarted event
 3. Dispatch the step runner for the stage type
 4. Read exit code:
 0 (pass) → emit DeploymentRunStageCompleted, continue to next stage
 1 (fail) → emit DeploymentRunStageFailed
 on_failure = 'halt' → run status = 'failed', exit
 on_failure = 'requeue' → items back to 'implemented', run cancelled, exit
 on_failure = 'skip' → log warning, continue
 2 (needs-capability) → run halted, exit (items stay 'release')
 2 (human-approval) → run halted, exit (items stay 'release')

On final stage complete:
 Set run status = 'succeeded'
 Atomically derive and persist deployment_runs.carried_work from the previous succeeded lineage
 Check all blocking run-level QA satisfied
 Set member items status = 'done' when member items exist

Carried-work attribution is not membership: resolved riding items and bare
commits are recorded on the run only, so they cannot enter the member-item
lifecycle path.
```

## No-Flow Fast Path

For current `release_stage` definitions, items without a deployment flow (or
with an `internal`-type flow) skip the multi-stage pipeline. Usher closes its
bound segment directly from `implemented` to `done`. Other delivery policies
do not inherit this fast path.

## Ephemeral Environments

Ephemeral environments are an implementation-skill capability, not a
deployment-flow stage. The current task-graph workflow uses them inside its
definition-bound `conduct` segment, commonly while moving from
`implementing` toward `reviewing-implementation`:

- **Creation:** GitHub Actions spins up an ephemeral environment on branch push (triggered by the CI workflow, not by the Usher).
- **Tracking:** Yoke tracks active environments in the `ephemeral_environments` DB table (keyed by branch name).
- **Conduct integration:** Conduct polls for environment health and makes the
  environment URL available to materialized QA cases. Cases whose method
  configuration requires a base URL execute against that exact environment.
- **Lifecycle:** Environments are torn down when the branch is merged or deleted (handled by the CI cleanup workflow, not by Yoke).
