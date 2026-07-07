# Advance — Browser QA: Deployment Checks

Extracted from `browser-qa.md`. Covers push, deployment polling, env status tracking, and post-poll escalation. Read and follow this file when `browser-qa.md` directs you here.

**Context variables** (inherited from router): `{N}`, `_item_project`, `_wt_branch`, `_eph_url`

> **Boundary note:** env-row writes in this document are source-dev/admin
> internals of the advance deployment check. Use the registered `yoke
> ephemeral-env update ENV-ID FIELD VALUE` wrapper for env status,
> workflow_run_id, URL, and deployed_sha updates. Project reads (`yoke
> projects get`), browser context (`yoke qa browser-context get`), and
> workflow polling (`yoke github-actions check-ci`) are also registered
> surfaces.

---

## Push Branch and Redeploy (redeploy-check step)

**Skip if project lacks `ephemeral-env` capability.**

**Issue items only.** Epics do not have a single worktree branch; their task lanes advance through `/yoke conduct` which owns per-lane ephemeral deployments. The `ephemeral-env` capability check above already gates this block — epic items do not have that capability — so the `_wt_branch` read below is always for an issue.

### Resolve push target

```bash
_wt_branch=$(yoke items get {N} worktree 2>/dev/null) || true
_push_repo=$(yoke projects get --project "$_item_project" --field repo_path 2>/dev/null) || true
_push_repo=${_push_repo:-$(git rev-parse --show-toplevel)}
_push_path="$_push_repo/.worktrees/$_wt_branch"
_git_dir="$_push_path"
if [ ! -d "$_push_path" ]; then
 _git_dir="$_push_repo"
fi

_head_sha=$(git -C "$_git_dir" rev-parse HEAD 2>/dev/null) || true
```

### Push latest code

```bash
if [ -d "$_push_path" ]; then
 _push_output=$(git -C "$_push_path" push origin "$_wt_branch" 2>&1)
else
 _push_output=$(git -C "$_push_repo" push origin "$_wt_branch" 2>&1)
fi
_push_exit=$?
```

Push failure → **block**: cannot redeploy. Do NOT update status.

### "Everything up-to-date" short-circuit

After a successful push, check if the output indicates nothing was pushed:

```bash
_up_to_date=$(printf '%s' "$_push_output" | grep -c "Everything up-to-date") || true
```

If `_up_to_date` is non-zero, verify the ephemeral environment is actually healthy before short-circuiting. The push may return "Everything up-to-date" while the deployment workflow from a prior push is still building (stale screenshots when short-circuit fired before deploy finished):

```bash
_env_id=$(python3 -m yoke_core.cli.db_router query "SELECT id FROM ephemeral_environments WHERE project_id=(SELECT id FROM projects WHERE slug='${_item_project}') AND branch='$_wt_branch' ORDER BY id DESC LIMIT 1" 2>/dev/null) || true
_env_status=""
if [ -n "$_env_id" ]; then
 _env_status=$(python3 -m yoke_core.cli.db_router query "SELECT status FROM ephemeral_environments WHERE id='$_env_id'" 2>/dev/null) || true
fi
```

- If `_env_status` is `healthy`: safe to short-circuit. Update `deployed_sha` and skip to step 5d.c:
 ```bash
 if [ -n "$_env_id" ] && [ -n "$_head_sha" ]; then
 yoke ephemeral-env update "$_env_id" deployed_sha "$_head_sha"
 fi
 ```
 > **Ephemeral short-circuit:** push returned "Everything up-to-date" and env status is healthy — skipping deployment poll.

- If `_env_status` is NOT `healthy` (e.g., `pending`, `starting`, `failed`, or empty): do NOT short-circuit. The deployment from a prior push may still be building. Fall through to workflow-poll step to find and poll the workflow run.
 > **No short-circuit:** push returned "Everything up-to-date" but env status is `{_env_status}` — deployment may still be in progress. Polling workflow run.

### Store Deployed SHA

After a successful push that delivered new code, update the deployed SHA so future advance attempts can detect "Everything up-to-date":
```bash
_env_id=$(python3 -m yoke_core.cli.db_router query "SELECT id FROM ephemeral_environments WHERE project_id=(SELECT id FROM projects WHERE slug='${_item_project}') AND branch='$_wt_branch' ORDER BY id DESC LIMIT 1" 2>/dev/null) || true
if [ -n "$_env_id" ] && [ -n "$_head_sha" ]; then
 yoke ephemeral-env update "$_env_id" deployed_sha "$_head_sha"
fi
```

## Wait for Ephemeral Deployment (workflow-poll step)

**Skip if short-circuited above ("Everything up-to-date" AND env status is `healthy`).** If the push was "Everything up-to-date" but env status is NOT `healthy`, this step MUST still run.

Resolve repo slug and workflow, find run for pushed commit:
```bash
_repo_slug=$(yoke projects get --project "$_item_project" --field github_repo 2>/dev/null) || true
_eph_workflow="${_item_project}-ephemeral.yml"

sleep 5
if _run_id=$(python3 -m yoke_core.domain.github_actions find-run "$_repo_slug" "$_eph_workflow" "$_head_sha" 2>/dev/null); then
 _find_exit=0
else
 _find_exit=$?
 _run_id=""
fi
```

Retry once after 10s if not found:
```bash
if [ "$_find_exit" -ne 0 ] || [ -z "$_run_id" ]; then
 sleep 10
 if _run_id=$(python3 -m yoke_core.domain.github_actions find-run "$_repo_slug" "$_eph_workflow" "$_head_sha" 2>/dev/null); then
 _find_exit=0
 else
 _find_exit=$?
 _run_id=""
 fi
fi
```

If still not found → **hard-block**. Do NOT proceed with browser QA against a stale deployment:
```bash
if [ "$_find_exit" -ne 0 ] || [ -z "$_run_id" ]; then
 _env_id=$(python3 -m yoke_core.cli.db_router query "SELECT id FROM ephemeral_environments WHERE project_id=(SELECT id FROM projects WHERE slug='${_item_project}') AND branch='$_wt_branch' ORDER BY id DESC LIMIT 1" 2>/dev/null) || true
 if [ -n "$_env_id" ]; then
 yoke ephemeral-env update "$_env_id" status "failed"
 fi
 # HARD BLOCK — do NOT update status, do NOT proceed to browser orchestrator
fi
```
> **Blocked:** No ephemeral workflow run found for commit `{_head_sha}` after retry. Cannot run browser QA against a stale or missing deployment. Env marked `failed`.
>
> Troubleshoot: check that `{_eph_workflow}` exists in the repo and that the push triggered it.

**When find-run succeeds (exit 0):** Persist `workflow_run_id` to the env record immediately and transition status from `pending` to `starting`:
```bash
_env_id=$(python3 -m yoke_core.cli.db_router query "SELECT id FROM ephemeral_environments WHERE project_id=(SELECT id FROM projects WHERE slug='${_item_project}') AND branch='$_wt_branch' ORDER BY id DESC LIMIT 1" 2>/dev/null) || true
if [ -n "$_env_id" ] && [ -n "$_run_id" ]; then
 yoke ephemeral-env update "$_env_id" workflow_run_id "$_run_id"
 yoke ephemeral-env update "$_env_id" status "starting"
fi
```

Wait for completion via the registered GitHub Actions wrapper (30-minute timeout,
client-side polling over repeated `github_actions.check_ci` dispatches):
```bash
_ci_json=$(yoke github-actions check-ci "$_repo_slug" "$_eph_workflow" --branch "$_wt_branch" --wait --timeout 1800 --project "$_item_project" --json)
_ci_state=$(printf '%s' "$_ci_json" | python3 -c "import json,sys; print((json.load(sys.stdin).get('result') or {}).get('state') or '')")
case "$_ci_state" in
 passed) _deploy_status="healthy" ;;
 failed) _deploy_status="failed" ;;
 timeout) _deploy_status="waiting" ;;
esac
```

### Update Env Status After Poll

When the poll loop exits with a result, update the env record immediately — before proceeding to browser QA or blocking. This ensures retry paths can short-circuit via the "Everything up-to-date" check (redeploy-check step) instead of re-polling:

```bash
if [ "$_deploy_status" = "healthy" ] && [ -n "$_env_id" ]; then
 yoke ephemeral-env update "$_env_id" status "healthy"
fi
```

- `healthy` → env record updated to `healthy`, proceed
- `failed` → fetch failed-step log tail, then **block** advance
- `waiting` (timeout) → **hard-block**: `**Blocked:** Ephemeral deployment timed out after 1800s (~30 min). Cannot run browser QA against an incomplete deployment. The workflow run `{_run_id}` did not reach a terminal state. Check GitHub Actions for details.`

---

After deployment checks pass, return to `browser-qa.md` to continue with the orchestrator and evaluation phases.
