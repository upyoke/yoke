# Usher — Finalize

Step 9: Completion report, idempotency rules, pipeline failure recovery, and operational notes.

---

## Step 9: Completion Report

```
===================================================================
USHER COMPLETE
===================================================================

Results:
 YOK-{id} "{title}" -- done (run-{date}-{seq})
 YOK-{id} "{title}" -- done (internal, no run)
 YOK-{id} "{title}" -- paused (run-{date}-{seq}, awaiting approval)
 YOK-{id} "{title}" -- halted (usher-halt-deploy-stage-failure)
 YOK-{id} "{title}" -- halted (usher-halt-deploy-infra-failure)
 YOK-{id} "{title}" -- halted (usher-halt-merge-failure)
 YOK-{id} "{title}" -- halted (usher-halt-unexpected, exit {code})

Deployment runs created:
 {run-id}: project={project}, flow={flow}, target={target}, items={count}, status={status}

{If paused runs:}
Paused runs (awaiting approval):
 {run-id}: stage {stage} -- /yoke usher --resume YOK-{N}

{count} items completed. {paused_count} awaiting approval. {halted_count} halted. {run_count} deployment run(s) created.
```

For halt rows, name the halt-class reason that the halt branch already released the work claim with. Do NOT label a halted row "completed" — the halt-class string is the audit signal downstream doctor/Ouroboros consume.

## Idempotency

- Re-run on `done` items: silently skipped.
- Re-run on `release` items: skip merge, proceed to deployment routing.
- Re-run after approval: `--deploy-only` picks up from approved stage. Step 8c3b finds existing run.
- Re-run after failure: merges skipped for merged items; existing run found, deployment resumes.
- Partial batch: succeeded items at `done`/`release` skipped on re-run.

## Pipeline Failure Recovery

### Diagnose

```bash
yoke deployment-runs get {run-id}
yoke deployment-flows stages {flow-id}
```

Key fields: `status` (overall), `current_stage` (where stopped, `-failed` suffix = failure point).

### Classify halt cause

After diagnosing the failure point, classify the cause. If the halt cause matches an **infrastructure class** — operator action on systems outside the repo's diff — surface a follow-up suggestion before the recovery options below. Suggesting a follow-up does not replace the recovery options; it ensures the underlying infra issue is captured as its own backlog item so the operator does not have to remember both "fix the secret" and "resume usher" at the same time.

Infrastructure-class signals (string-match against the failing stage's logs, the run's `deploy_log` field, or the operator's recall of the live failure):

- **GitHub Actions / CI runner** — `deploy_key`, `Actions secret`, `workflow_dispatch`, `runner offline`, `GitHub token`, `permission denied (publickey)` against a CI host.
- **SSH / external host** — `ssh:`, `Permission denied`, `Host key verification failed`, `Connection refused` against a deploy target.
- **External secret / credential** — `Bad credentials`, `401 Unauthorized` against a third-party API the deploy stage calls, missing env var named in a stage script.
- **Cloud provider / AWS / network** — `AccessDenied`, `RequestLimitExceeded`, `DNS lookup failed`, regional outages.

When the halt cause classifies as infrastructure, render this suggestion alongside the recovery options:

```
INFRA-CLASS HALT DETECTED
Component: {component-name, e.g., "GitHub Actions deploy_key", "AWS S3 credentials"}

File a follow-up so the underlying infra issue is tracked separately from this run:

  /yoke idea "Fix {component-name} blocking YOK-{N} deploy"

Then return here and pick a recovery option below to unstick the current run.
```

Pick `{component-name}` to name the failing surface specifically (`"buzz GitHub Actions deploy_key secret"`, `"prod SSH host key"`, `"AWS deploy credentials"`) — generic phrasing like `"CI"` or `"infra"` does not help the operator recognize what to fix. Code-class halts (a stage script raising an exception against this repo's code) are NOT infrastructure-class; surface no suggestion for those and fall through to the recovery options.

### Option A: Retry failed stage

When: transient failure, cause resolved. Re-run pipeline (reads `current_stage`, strips `-failed`, retries):
```bash
python3 -m yoke_core.domain.deploy_pipeline {run-id}
```

### Option B: Skip a stage

When: non-critical stage or manually verified. Update stage, re-run:
```bash
yoke deployment-runs update {run-id} current_stage {next-stage-name}
python3 -m yoke_core.domain.deploy_pipeline {run-id}
```

### Option C: Manual completion

When: unrecoverable but manually verified. Both steps required in order:
```bash
yoke deployment-runs update {run-id} status succeeded
python3 -m yoke_core.tools.watch_merge done-transition -- {N} --skip-deploy
```

> **Warning:** Always use `--skip-deploy` when manually completing. Setting `status=succeeded` without it creates contradictory state.

### Option D: Abort the run

```bash
yoke deployment-runs update {run-id} status failed
```

Items remain at `release`. Re-attempt later or pull back to `implemented`.

## Release Manual Work Claims

Release reasons split by exit class. The four halt-class strings are terminal release intents per `yoke_core.domain.release_intent_classification.TERMINAL_RELEASE_INTENTS`; `completed` is reserved for the successful finalize path.

- **Complete exits (item reached `done`):** release the work claim with `reason: "completed"`.
- **Halt exits (merge halt, deploy infra failure, deploy stage failure, unexpected exit):** the halt branch in `merge.md` / `deploy.md` already released the work claim with the matching halt-class reason (`usher-halt-merge-failure`, `usher-halt-deploy-infra-failure`, `usher-halt-deploy-stage-failure`, `usher-halt-unexpected`) BEFORE control returned to finalize. Finalize MUST NOT re-release a claim it does not hold and MUST NOT overwrite the halt-class `release_reason_intent` audit value with `completed`. Skip the release loop for any item the halt branch already released.

For each `_usher_item` in `{collected_items}` whose claim is still held by this session (complete exits only):

```json
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim_id>},
  "intent": "usher_complete",
  "payload": {"claim_id": <claim_id>, "reason": "completed"}
}
```

Release failures surface as response errors but do not block the next item's release; the next-turn doctor surfaces orphaned claims if any slip through.

## Notes

- **Run-based deployment.** Multiple items with same project+flow grouped into single run. Pipeline called once per run.
- **LLM-based dependency ordering.** Usher uses LLM reasoning for ordering, operator for conflict resolution.
- **Lock management.** No weave lock. Merge serialization handled by the retained merge watcher (`python3 -m yoke_core.tools.watch_merge merge-worktree`).
- **Board rebuild.** Each done-transition triggers rebuild internally.
- **Push to origin.** Each `python3 -m yoke_core.tools.watch_merge done-transition` run preserves the underlying done-transition push behavior.
- **Cold-start capable.** All state read from DB.
- **Pre-merge ephemeral verification.** For flows with `ephemeral-verify`, verification runs before merge (Step 7c). After merge, pipeline skips it via `--from-stage`.
- **Preview-environment targeting.** Multiple targets → operator selection. Release lineage tracking for preview-to-prod progression.
- **Run-level QA.** At run creation, materializes blocking QA requirements from flow defaults.
