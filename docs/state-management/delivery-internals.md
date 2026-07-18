# Delivery Lifecycle Internals

Detail pages for the delivery pipeline owned by the Usher. The high-level ownership boundary (`implemented → release → done`) and the handoff from Polish lives in [state-management.md](../state-management.md#delivery-lifecycle); this file covers the run mechanics, halt states, executor types, and ephemeral environments referenced from there.

## Deployment Runs

Stage authority now lives on the `deployment_runs` row (`current_stage` column), not on individual items. A deployment run groups one or more items into a single pipeline execution for ticket delivery.

**Run statuses:** `created → executing → succeeded | failed | cancelled`

**Item lifecycle during a run:**
- Items remain at `implemented` while the run is `created` (queued but not executing)
- Items transition to `release` when the run starts `executing`
- Items transition to `done` when the run `succeeded` and all blocking `post_deploy` and `manual_acceptance` QA is satisfied

**The `deploy_stage` column** on the `items` table is retained as a read cache during the transition period, kept in sync with the run's `current_stage`. New code should read stage from the run, not from the item. See `packages/yoke-core/src/yoke_core/domain/approval.py` constants `STAGE_AUTHORITY_FIELD` (`current_stage`) and `STAGE_CACHE_FIELD` (`deploy_stage`) for the canonical machine-readable distinction.

## Halt States

> **Vocabulary note:** Halt states (`awaiting-approval`, `needs-capability`) are **run-level conditions**, not item lifecycle statuses. Items at a halted run remain at `status=release`. The canonical halt-state registry is `packages/yoke-core/src/yoke_core/domain/approval.py`. The canonical lifecycle registry is `packages/yoke-core/src/yoke_core/domain/lifecycle.py`.

Two conditions act as halt states during deployment run execution (items at these halt states remain at `status=release`):

**`needs-capability`** — An executor script detected a missing or misconfigured project capability (exit code 2). The run is blocked until the operator configures the capability in `project_capabilities` and re-runs `/yoke usher YOK-N`. The Usher does not attempt to proceed or guess — it exits cleanly.

**Human approval gate** — When the pipeline encounters a stage with `executor: "human-approval"`, the run halts at that stage. The item is blocked until the operator runs `/yoke approve YOK-N [--note "..."]`, which advances the run's `current_stage` to the next stage in the flow. The operator then re-runs `/yoke usher YOK-N` to resume.

**External projects:** When a project-owned `github-actions-workflow` stage
targets a protected GitHub environment, GitHub's native protection rules pause
the Actions run. The Usher records the wait on the deployment run; approval
happens in GitHub, not through `/yoke approve`. Once protection is satisfied,
the Usher's next poll sees the workflow resume and advances the declared stage.
The project repository's `.yoke/deployment-flows.json` owns the stage chain and
workflow filenames.

Both halt states are visible on the board. Items at `release` with halted runs are not counted as WIP.

## Capability Self-Invention

When an executor encounters a missing capability, it follows the capability self-invention protocol:

1. Executor exits with code 2 and writes capability details to stdout (`CAPABILITY_NEEDED`, `REASON`, `TEMPLATE`)
2. Usher records the capability need as an event via `yoke_core.domain.events.emit_event`
3. If the template is novel (`TEMPLATE = 'NEW'`), Usher saves it to `capability_templates`
4. Usher halts the deployment run and exits (items stay at `release`)
5. Operator configures the capability (adds row to `project_capabilities`) and re-runs `/yoke usher YOK-N`

## Human Approval Gate

When the pipeline encounters a `human-approval` executor stage:

1. Pipeline halts the deployment run at the approval stage and exits with code 2
2. Items remain at `status = 'release'` with the run halted
3. Operator reviews and runs `/yoke approve YOK-N [--note "..."]`
4. Approve advances the run's `current_stage` to the next stage in the flow
5. Operator re-runs `/yoke usher YOK-N` to continue from that next stage

## Executor Dispatch

The Python pipeline owner is `yoke_core.domain.deploy_pipeline`. The pipeline dispatches each stage by `executor` (or by `kind` for governed migration stages). Known current types:

| Stage shape | Executor/kind | Description | Exit codes |
|-----------------|--------|-------------|------------|
| executor | `auto` | No-op stage (`merged`, `complete`) | 0 (always) |
| kind | `migration_apply` | Verifies governed migration evidence for member items; item-less runs pass with explicit run-stage evidence | 0=pass, 1=failure |
| executor | `environment-activate` | Ensures the target environment host is running and reachable | 0=ready, 1=failure |
| executor | `core-container-deploy` | Builds/pushes/reuses the pinned Yoke core image and converges the target host | 0=deployed, 1=failure |
| executor | `health-check` | HTTP GET; Yoke core env checks require x-request-id echo | 0=healthy, 1=failure |
| executor | `ephemeral-deploy` / `ephemeral-teardown` / `ephemeral-verify` | Manages preview environments | 0=pass, 1=failure |
| executor | `human-approval` | Halts pipeline for human approval | Pipeline exits 2 |
| executor | `github-actions-workflow` | Triggers and polls GitHub Actions workflow | 0=success, 1=failed |

**`github-actions-workflow`:** Used for external projects where deployment is managed by GitHub Actions. The Python deploy pipeline resolves repository authority from DB/project capabilities, triggers or finds the configured workflow run, stores the workflow run id in deployment telemetry, and polls until the workflow reaches a terminal state. GitHub Actions run states map as follows:

- `queued` / `waiting` → poll returns exit 2, pipeline continues polling
- `in_progress` → poll returns exit 3, pipeline continues polling
- `completed` + `success` → poll returns exit 0, pipeline advances to next stage
- `completed` + `failure` → poll returns exit 1, `deploy_stage = '{stage-name}-failed'`, halt

**Yoke core health-check:** Env-resolved Yoke core health checks prove three things before the release is healthy: public `/v1/health` responds, the response echoes the request id, and the response `build` matches the image tag the pipeline deployed. After that passes, the health stage fetches the target HTTPS env's `/v1/cli/manifest` and compares it to this checkout's local CLI manifest. A release fails if the deployed API is missing a local wrapped subcommand such as `strategy.doc.create`; the fix is to deploy/update the Yoke API, not to bypass the HTTPS path.

## Usher State Machine

```
Entry: item.status = 'implemented'

1. Create deployment_run (status = 'created')
2. Enroll items via deployment_run_items for item-bound delivery; skip for environment-level deploys
3. Materialize run-level QA requirements
4. Set run status = 'executing'; set member items to `release` only when member items exist

For each stage in deployment_flow.stages:
 1. Set run.current_stage = stage.name
 2. Emit DeploymentRunStageStarted event
 3. Dispatch executor for stage type
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
 Check all blocking run-level QA satisfied
 Set member items status = 'done' when member items exist
```

## No-Flow Fast Path

Items without a deployment flow (or with an `internal`-type flow) skip the multi-stage pipeline. The Usher transitions them directly from `implemented` to `done`.

## Ephemeral Environments

Ephemeral environments are a **conduct-phase capability**, not a deployment flow stage. They provide a live preview environment for testing during the `implementing → reviewing-implementation` phase:

- **Creation:** GitHub Actions spins up an ephemeral environment on branch push (triggered by the CI workflow, not by the Usher).
- **Tracking:** Yoke tracks active environments in the `ephemeral_environments` DB table (keyed by branch name).
- **Conduct integration:** The Conduct polls for environment health and injects the environment URL into the Tester's dispatch prompt so integration tests can run against a live instance. The Tester runs the project's `e2e` command from the `command_definitions` family with `BASE_URL={environment_url}` injected as an environment variable.
- **Lifecycle:** Environments are torn down when the branch is merged or deleted (handled by the CI cleanup workflow, not by Yoke).
