# Usher — Post-Merge Deployment Routing

Step 8: Route merged items through deployment pipelines. Skip if `--merge-only`.

**Events for verification.** Item-bound runs can be checked with `yoke events query --event-name DeploymentRunStageCompleted --item {N}` before advancing to done. Item-less environment runs have no item id; check them by run id in deployment-run state and run-level events instead.

**Local command-shaped deploy surfaces.** On machines whose active env is HTTPS `prod`, prepend `YOKE_ENV=prod-db-admin` when invoking retained `db_router runs ...` creation/preview forms or the retained `watch_deploy` wrapper; those are local-runtime command-shaped surfaces that need the local-Postgres admin env. Run/flow reads, run updates, and target-env resolution use the dispatcher-backed deployment flow/run wrappers.

**Context variables** (set by prior phases): merged items, `_MERGE_ONLY`, `_pre_merge_verified`, `_eph_next_stage`

If `_MERGE_ONLY`: report merge-only complete, **stop**.

---

## Step 8a: Group items by (project, deployment_flow)

For each merged item, read `deployment_flow` and `project` through the typed `items.get` function (typed reads, not shell `items get`).

Two categories:
- **Internal flow:** `deployment_flow` is `yoke-internal`, `buzz-internal`, empty, or null
- **Deployment flow:** grouped by `(project, deployment_flow)`

## Step 8b: Route A — Internal flow items (no run)

The done-transition engine is a retained Yoke-internal boundary; run it through the merge watcher, then handle exit codes:

```bash
python3 -m yoke_core.tools.watch_merge done-transition -- {N} --skip-deploy
```

For any non-zero exit code that revert-to-implemented requires, call `lifecycle.transition.execute` to revert the item from `release` back to `implemented` (the handler runs the standard rollback gate, posts the GitHub status-change comment, and emits `ItemStatusChanged`):

```json
{
  "function": "lifecycle.transition.execute",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "item", "item_id": {N}},
  "intent": "usher_rollback_to_implemented",
  "payload": {"target_status": "implemented", "source_status": "release", "reason": "<exit-code summary>"}
}
```

Exit-code dispatch:

- **Exit 0:** Success — item transitioned to done. Continue to next item.
- **Exit 1:** Merge failure. Revert to `implemented`, halt batch. Report: `[Route A] YOK-{N}: done-transition merge failure (exit 1). Reverted to implemented.`
- **Exit 2:** CWD/argument/validation error. Revert to `implemented`, halt batch. Report: `[Route A] YOK-{N}: done-transition validation error (exit 2). Reverted to implemented.`
- **Exit 3:** Simulation gate failure (epic) or merge conflicts requiring agent resolution. Revert to `implemented`, halt batch. Report: `[Route A] YOK-{N}: done-transition blocked by simulation gate or conflicts (exit 3). Reverted to implemented.`
- **Exit 4:** User files at risk — **HARD STOP**. Revert to `implemented`. Report: `[Route A] YOK-{N}: user files at risk (exit 4). Reverted to implemented. Manual review required.`
- **Exit 7:** Deployment flow guard. The item has a deployment flow that requires pipeline execution, but `--skip-deploy` was passed. Revert to `implemented`. Report: `[Route A] YOK-{N}: deployment flow guard (exit 7). This item needs Route B (deployment pipeline), not Route A. Reverted to implemented. Re-run usher without --skip-deploy or verify the item's deployment_flow field.`
- **Exit 8:** Empty worktree branch — the item's worktree branch has no commits diverging from main. This is the evidence-only guard. Revert to `implemented`. Report: `[Route A] YOK-{N}: empty worktree branch (exit 8). This is an evidence-only item with no code changes. Reverted to implemented.`
  **Recovery:** The canonical remediation is the evidence-only path — the item should have been advanced with `--no-worktree` (which sets `worktree = NULL`), or the operator should clear the worktree field by calling `items.scalar.update` with `payload.field="worktree"`, `payload.value=null`. Then re-run `/yoke usher YOK-{N}`.
- **Exit 99:** Self-modifying bootstrap — the underlying done-transition engine re-executes itself. This is handled internally by the launcher and should never surface to usher. If it does, treat as unexpected and apply the catch-all below.
- **Any other non-zero exit (catch-all):** Unexpected failure. Revert to `implemented` so the item is never stranded in `release`. Report: `[Route A] YOK-{N}: unexpected done-transition failure (exit {code}). Reverted to implemented. Investigate the done-transition output above.`

## Step 8c: Route B — Item-bound deployment flow groups

For each `(project, flow)` group:

### 8c1-8c7: Compose the run

Lead with the composed surface `runs start-for-item`, which folds resolve-target-env, create-run, add-item, and validate-composition into a single invocation:

```bash
python3 -m yoke_core.cli.db_router runs start-for-item {item-id} \
    [--project {project}] [--flow {flow}] [--target-env {target-env}] \
    [--release-lineage {lineage-id}] [--created-by {actor}]
```

Multiple resolvable target envs → `AskUserQuestion` for selection, then re-run with `--target-env`. Validation failure → halt.

Preview-flow side decisions wrap the composed call (these are not folded into `start-for-item`):

- **Before** `start-for-item`: check occupancy via `runs check-preview-occupancy {project} {target_env}`; if occupied, `AskUserQuestion` (overwrite / new name / abort). For a new lineage, `runs lineage-create` first and pass the result as `--release-lineage`.
- **Resume an existing run** instead of starting a new one when `runs find-by-item {first-item-id} --status executing` returns a row — skip to 8c8.
- **After** `start-for-item`: `runs claim-preview {run-id} {project} {target_env}` to attach the preview to the run.

The target-env resolver is `yoke deployment-runs resolve-target-env`; the other internal per-step forms (`runs create-run`, `runs add-item`, `runs validate-composition`) remain operator/debug surfaces. Prefer the composed call for item-bound delivery.

### Environment-level deploys (no item)

If the operator asks for a Yoke prod/stage environment redeploy without an attached backlog item, do **not** route through `start-for-item` and do **not** invent an item. Resolve the target branch SHA from an explicit Yoke source checkout, create a zero-item deployment run from the flow id, and execute that run id with the resolved image tag:

```bash
target_env=prod
target_branch=main
source_checkout=<source-checkout>
git -C "$source_checkout" fetch origin "$target_branch"
deploy_image_tag="$(git -C "$source_checkout" rev-parse --short=12 FETCH_HEAD)"
YOKE_ENV=prod-db-admin python3 -m yoke_core.cli.db_router runs create-run yoke "yoke-${target_env}-release" --target-env "$target_env" --created-by operator
YOKE_ENV=prod-db-admin python3 -m yoke_core.tools.watch_deploy -- {run-id} --image-tag "$deploy_image_tag"
```

`yoke-prod-release` / `yoke-stage-release` are deployment-flow ids; the first command prints the concrete `run-...` id. Zero rows in `deployment_run_items` are valid for these environment-level runs. `deploy_pipeline` skips item branch verification and item status writes, while the flow still gates the declared environment branch (`main` for prod, `stage` for stage), runs env activation, deploys the explicitly tagged core image, checks public health, and records `deployment_runs.current_stage` / `status`.

### 8c8: Run-level QA seeding
**Do NOT manually seed** — the retained deploy pipeline invoked by `python3 -m yoke_core.tools.watch_deploy` calls the internal deploy QA recorder automatically.

### 8c9: Execute deployment pipeline

**Branch ancestry check** (defense in depth) — verify branch is ancestor of the flow's gate branch: the target env's declared deploy branch (`environments.settings.git.branch` — `main` for prod flows, `stage` for stage flows), or `main` when the flow has no env-declared branch. The pipeline enforces the same gate internally (`resolve_flow_gate_branch`).

**Long-running execution:** `deploy_pipeline` polls external CI systems and can run for several minutes (default timeout: 30 min). Use the shared deploy watcher so agents do not hand-author filters. Under Codex/native shell, run it foreground and let the PTY stream. Under Claude Code, run `watch_deploy --print-streaming-pair` and paste the printed background/progress pair into the harness surfaces. Await completion; do not poll. The full anti-polling rule lives in `runtime/harness/claude/rules/session.md` and is enforced by `runtime/api/domain/lint_long_command_polling.py`.

```bash
# Codex/native shell:
if [ "$_pre_merge_verified" = "1" ] && [ -n "$_eph_next_stage" ]; then
 YOKE_ENV=prod-db-admin python3 -m yoke_core.tools.watch_deploy -- {run-id} --from-stage "$_eph_next_stage"
else
 YOKE_ENV=prod-db-admin python3 -m yoke_core.tools.watch_deploy -- {run-id}
fi
```

```bash
# Claude Code:
YOKE_ENV=prod-db-admin python3 -m yoke_core.tools.watch_deploy --print-streaming-pair -- {run-id}
```

**Exit 0:** Run done-transition for each item: `python3 -m yoke_core.tools.watch_merge done-transition -- {N} --skip-deploy`

**Exit 1 (HALT — `usher-halt-deploy-stage-failure`):** Stage failed. For every member item of the run, release the work claim with `usher-halt-deploy-stage-failure` BEFORE printing resume/recovery instructions. If the release call itself fails, the halt summary MUST say the release failed and include the failure class / holder when available — do not print a clean recovery summary while the claim is still live. Operator/debug adapter (dispatches `claims.work.release`):

```bash
yoke claims work release --item YOK-{N} --reason usher-halt-deploy-stage-failure
```

The four `usher-halt-*` values are terminal release intents per `yoke_core.domain.release_intent_classification.TERMINAL_RELEASE_INTENTS`. Do NOT use `completed` for a halt path. After release, halt the batch and surface resume instructions.

**Exit 2:** Awaiting approval — invoke the `/yoke approve YOK-{N}` skill ([`.agents/skills/yoke/approve/SKILL.md`](../approve/SKILL.md)):

```
/yoke approve YOK-{N} [--run {_run_id}] [--note "..."]
```

What `/yoke approve` does internally (canonical recipe — do not duplicate inline):
1. Resolves run context (run id, next stage, member item ids) via `python3 -m yoke_core.api.service_client apply-approval {item_num}`.
2. Surfaces the ephemeral preview URL by querying the `DeploymentRunStageCompleted` events for the run.
3. Prompts via `AskUserQuestion` ("Yes, approve and continue" / "No, pause for later"). Pause → report paused state, continue to next group.
4. Emits `DeploymentApprovalGranted` via `yoke events emit`.
5. Updates `runs current_stage` and dual-writes each member item's `deploy_stage` via `items.scalar.update`.
6. Re-invokes `python3 -m yoke_core.tools.watch_deploy -- {run-id} --from-stage {next-stage}` to resume the pipeline.

The re-invoked pipeline may surface another exit 2 — re-invoke `/yoke approve YOK-{N}` for each successive gate until the pipeline completes (exit 0), fails (exit 1), or the operator pauses (exit 3).

**Exit 3 (HALT — `usher-halt-deploy-infra-failure`):** Setup / infrastructure error before any stage ran (preview claim, lineage, validation). For every member item of the run, release the work claim with `usher-halt-deploy-infra-failure` BEFORE printing recovery instructions. Same release-failure contract as exit 1 (halt summary names the release failure if the release call itself fails). Operator/debug adapter:

```bash
yoke claims work release --item YOK-{N} --reason usher-halt-deploy-infra-failure
```

After release, halt the batch.

---

After all groups processed, return to router for finalize phase.
