# Usher — Post-Merge Deployment Routing

Step 8: Route merged items through deployment pipelines. Skip if `--merge-only`.

**Run state for verification.** Check item-bound delivery through
`yoke deployment-runs get {run-id}`; events are audit telemetry, not the
success authority.

**Context variables** (set by prior phases): merged items, `_MERGE_ONLY`, `_pre_merge_verified`, `_eph_next_stage`

If `_MERGE_ONLY`: report merge-only complete, **stop**.

---

## Step 8a: Group items by (project, deployment_flow)

For each merged item, read `deployment_flow` and `project` through the typed `items.get` function (typed reads, not shell `items get`).

Two categories:
- **Internal flow:** `deployment_flow` is empty/null or ends in the registered
  project convention `-internal`
- **Deployment flow:** grouped by `(project, deployment_flow)`

Usher does not know project-specific flow ids or release topology. It executes
the item's active registered flow exactly as defined; disabled flows cannot be
assigned or start a run.

## Step 8b: Route A — Internal flow items (no run)

The done-transition engine is the project-agnostic internal-delivery boundary;
run it through the merge watcher, then handle exit codes:

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
- **Exit 8:** Empty worktree branch — the item's worktree branch has no commits diverging from the project's default branch. This is the evidence-only guard. Revert to `implemented`. Report: `[Route A] YOK-{N}: empty worktree branch (exit 8). This is an evidence-only item with no code changes. Reverted to implemented.`
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

### 8c8: Run-level QA seeding
**Do NOT manually seed** — `yoke_core.domain.deploy_pipeline` calls the internal deploy QA recorder automatically.

### 8c9: Execute deployment pipeline

**Branch ancestry check** (defense in depth) — verify the merged item commit is
an ancestor of the branch selected by the flow's project/environment policy.
The pipeline owns that resolution and enforces the same gate internally
(`resolve_flow_gate_branch`); Usher must not hardcode a project branch.

**Long-running execution:** `deploy_pipeline` polls external CI systems and can run for several minutes (default timeout: 30 min). Execute it through the harness long-command surface, await completion, and do not poll. The full anti-polling rule lives in `runtime/harness/claude/rules/session.md` and is enforced by `runtime/api/domain/lint_long_command_polling.py`.

```bash
if [ "$_pre_merge_verified" = "1" ] && [ -n "$_eph_next_stage" ]; then
 python3 -m yoke_core.domain.deploy_pipeline {run-id} --from-stage "$_eph_next_stage"
else
 python3 -m yoke_core.domain.deploy_pipeline {run-id}
fi
```

**Exit 0:** Run done-transition for each item: `python3 -m yoke_core.tools.watch_merge done-transition -- {N} --skip-deploy`

**Exit 1 (HALT — `usher-halt-deploy-stage-failure`):** Stage failed. For every member item of the run, release the work claim with `usher-halt-deploy-stage-failure` BEFORE printing resume/recovery instructions. If the release call itself fails, the halt summary MUST say the release failed and include the failure class / holder when available — do not print a clean recovery summary while the claim is still live. Operator/debug adapter (dispatches `claims.work.release`):

```bash
yoke claims work release --item YOK-{N} --reason usher-halt-deploy-stage-failure
```

The four `usher-halt-*` values are terminal release intents per `yoke_core.domain.release_intent_classification.TERMINAL_RELEASE_INTENTS`. Do NOT use `completed` for a halt path. After release, halt the batch and surface resume instructions.

**Exit 2:** Awaiting approval — halt and surface the exact Yoke run command
([`.agents/skills/yoke/approve/SKILL.md`](../approve/SKILL.md)):

```
yoke deployment-runs approve {_run_id} [--note "..."] --json
```

That registered mutation validates the exact executing run and approval stage,
atomically advances run and member-item stage state, and writes the Yoke audit
event. After the operator approves, re-run Usher with `--deploy-only`; it
resumes from the run's authoritative stage. Another approval stage produces
another exit 2 and requires another exact-run approval.

**Exit 3 (HALT — `usher-halt-deploy-infra-failure`):** Setup / infrastructure error before any stage ran (preview claim, lineage, validation). For every member item of the run, release the work claim with `usher-halt-deploy-infra-failure` BEFORE printing recovery instructions. Same release-failure contract as exit 1 (halt summary names the release failure if the release call itself fails). Operator/debug adapter:

```bash
yoke claims work release --item YOK-{N} --reason usher-halt-deploy-infra-failure
```

After release, halt the batch.

---

After all groups processed, return to router for finalize phase.
