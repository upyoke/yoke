# Dispatch Context — Ephemeral Environment Lifecycle

Extracted from `dispatch-context-gates.md`. Contains the full
ephemeral environment sub-step (5f-project-ephemeral) and browser QA execution.

---

## 5f-project-ephemeral. Ephemeral Environment Lifecycle (shared sub-step)

This sub-step runs **after** `5f-project` completes (for non-yoke projects only). It manages the full lifecycle of an ephemeral environment for the item's branch: create the DB record, trigger the workflow, poll for readiness, inject the URL into the Tester prompt, and tear down after testing.

**Boundary:** ephemeral environment creation and status / workflow-run / URL updates use the registered `yoke ephemeral-env create` and `yoke ephemeral-env update` wrappers. GitHub workflow triggering and run polling use the registered `yoke github-actions ...` family.

**Prerequisite:** The item's project must have the `ephemeral-env`
capability. Dispatch the `projects.capability.has` function call
(envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)):
`target = {kind: "global"}`, `payload = {project: "${_project}",
cap_type: "ephemeral-env"}`. Read `response.result.has` — when
`false`, skip this sub-step entirely. For non-yoke projects, emit a
visible warning so the operator notices when ephemeral env is
skipped — this prevents silent browser QA gaps.

**Resolve project repo slug and SSH host** (needed for GitHub
Actions API calls and URL construction). Project-capability config
payloads (`type='github'`, `type='ssh'`) are read through the
`yoke_core.domain.projects_capabilities.cmd_capability_get_settings`
helper (the authoritative Python read for a single project's
`project_capabilities` row by `type`). When orchestrating from shell, capability config reads remain
on the operator-debug `db_router query` surface as a retained
boundary — the structured function-call dispatch surface for
capability config payload reads (`projects.capability.config_get`,
analogous to the existing `projects.capability.has`) lands in a
follow-up; for now the raw query is the explicit retained boundary,
not a teaching anti-pattern:

```bash
# Retained-boundary: capability config payload read (operator-debug).
_github_config=$(yoke db read --format lines \
  "SELECT settings FROM project_capabilities WHERE project_id=(SELECT id FROM projects WHERE slug='${_project}') AND type='github'")
_ssh_config=$(yoke db read --format lines \
  "SELECT settings FROM project_capabilities WHERE project_id=(SELECT id FROM projects WHERE slug='${_project}') AND type='ssh'")
```

Parse the JSON `settings` payloads inline with `python3 -c
"import json,sys; ..."` to extract `repo_owner` / `repo_name`. The
inline `python3 -c` JSON read is the canonical retained-boundary
shape for capability config payload reads until the function-call
surface lands.

If `_repo_slug` is empty or malformed, log a warning and skip:
```
Warning: could not resolve repo slug for project '${_project}' — skipping ephemeral env
```

<!-- python3 -m yoke_core.domain.github_actions call signatures (from):
 python3 -m yoke_core.domain.github_actions trigger <repo-slug> <workflow-file> --ref <branch> --project <project>
 -> prints run ID on stdout, exit 0 on success, exit 4 on auth failure
 python3 -m yoke_core.domain.github_actions poll <repo-slug> <run-id> --project <project>
 -> exit 0=success, 1=failed, 2=waiting, 3=in-progress
 python3 -m yoke_core.domain.github_actions find-run <repo-slug> <workflow-file> <commit-sha> --project <project>
 -> prints run ID on stdout if found, exit 0=found, 1=not found
-->

#### E1. Create Environment Record

Create the ephemeral environment DB record **before** triggering the workflow. This ensures the record exists even if the workflow trigger fails.

```bash
# Branch naming contract: branch MUST be 'YOK-{id}' — see db-reference.md § ephemeral_environments
_env_id=$(yoke ephemeral-env create "${_project}" "YOK-${_id}" --item "YOK-${_id}")
```

The record is created with `status=pending` (the default). Store `_env_id` for use in subsequent steps. The status transitions to `starting` only after a workflow run is found.

#### E2. Trigger Ephemeral Environment Workflow

**Guard:** If the `python3 -m yoke_core.domain.github_actions` adapter is unavailable, skip E2-E3 and log:
```
Note: python3 -m yoke_core.domain.github_actions not available — ephemeral env record created but workflow not triggered
```
Set `_ephemeral_url` to `"pending"` and proceed to E4 (the Tester will see `Ephemeral URL: pending`).

**When python3 -m yoke_core.domain.github_actions is available:**

**Push the branch to origin before finding the workflow run.** The initial push at `advance active` time only deploys the branch at creation. Engineer changes committed during the conduct cycle are not deployed unless the branch is re-pushed. Always push before looking for the workflow run:

```bash
# Push the branch to trigger the ephemeral deploy workflow with latest changes
_wt_branch="YOK-${_id}"
git -C "${_worktree_path}" push origin "$_wt_branch" 2>&1
_push_exit=$?
```

If push fails (`_push_exit` non-zero), log a warning and proceed with find-run anyway (the original push may have triggered a deployment):
```
Warning: failed to push branch ${_wt_branch} to origin (exit ${_push_exit}). Ephemeral env may be stale.
```

If push succeeds:
```
Pushed branch ${_wt_branch} to origin — ephemeral redeploy triggered.
```

Find the workflow run triggered by the push:

```bash
# Get the HEAD commit SHA from the worktree
_head_sha=$(git -C "${_worktree_path}" rev-parse HEAD)

# Brief wait for GitHub to register the push-triggered run
sleep 5

# Find the workflow run for this commit
_eph_workflow="${_project}-ephemeral.yml"
_run_id=$(python3 -m yoke_core.domain.github_actions find-run "${_repo_slug}" "${_eph_workflow}" "${_head_sha}" --project "${_project}")
_find_exit=$?
```

If `find-run` exits with 1 (not found), retry after a short delay (GitHub may need time to register the push event):
```bash
if [ "$_find_exit" -ne 0 ]; then
 sleep 10
 _run_id=$(python3 -m yoke_core.domain.github_actions find-run "${_repo_slug}" "${_eph_workflow}" "${_head_sha}" --project "${_project}")
 _find_exit=$?
fi
```

If still not found, the workflow may not have been triggered. Update the env record and log:
```bash
yoke ephemeral-env update "${_env_id}" status "failed"
```
```
Warning: no ephemeral workflow run found for commit ${_head_sha} — env marked failed
```
Set `_ephemeral_url` to `"none"` and proceed to E4.

If `find-run` succeeds (exit 0), store `_run_id` and transition env from `pending` to `starting`:
```bash
yoke ephemeral-env update "${_env_id}" workflow_run_id "${_run_id}"
yoke ephemeral-env update "${_env_id}" status "starting"
```

#### E3. Poll for Healthy Status and Read URL

Poll the workflow run until it completes or times out. Use the sanctioned GitHub Actions waiter with a 30-minute timeout:

```bash
yoke github-actions wait-run "${_repo_slug}" "${_run_id}" --timeout 1800 \
 --project "${_project}"
_wait_exit=$?

case "$_wait_exit" in
 0) _env_status="healthy" ;;
 1) _env_status="failed" ;;
 3)
 _env_status="failed"
 echo "Warning: ephemeral env workflow timed out after 1800s"
 ;;
esac
```

**On success (`_env_status=healthy`):**

Derive the ephemeral URL using the project config's `domain` field and slug-based pattern. This is the same canonical URL derivation used by the advance path:
```bash
# Branch naming contract: branch MUST be 'YOK-{id}' — see db-reference.md § ephemeral_environments
_branch="YOK-${_id}"
# Slugify branch name (same logic as advance/environment.md and python3 -m yoke_core.domain.ephemeral_env)
_slug=$(printf '%s' "$_branch" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')

# The implementation-entry environment orchestrator reads the domain from
# DB-backed sites.settings.domains[0].domain_name. Operator-debug paths should
# inspect that DB setting; do not read retired project-local flat files.
_ephemeral_url="pending"
```

Update the env record:
```bash
yoke ephemeral-env update "${_env_id}" status "healthy"
yoke ephemeral-env update "${_env_id}" url "${_ephemeral_url}"
```

**On failure (`_env_status=failed`):**
```bash
yoke ephemeral-env update "${_env_id}" status "failed"
```
Set `_ephemeral_url` to `"none"`. Log the failure but do NOT block dispatch — the Tester can still run without an ephemeral environment.

#### E4. Inject URL and Browser Execution Instructions into Tester Prompt

The `_ephemeral_url` value (set by E3, or by the guard clause in E2) is already consumed by `5f-project` step d2's query or the `Ephemeral URL:` line in the project context block. If E1-E3 ran successfully and set the URL in the DB, the existing query in `5f-project` step d2 will pick it up.

**However**, since E1-E3 run after `5f-project`, the URL may not be in the DB yet when d2 runs. Therefore, after E3 completes, **overwrite** `_ephemeral_url` in the context block:

Update the `Ephemeral URL:` line in the context block with the resolved URL:
```
Ephemeral URL: {_ephemeral_url}
```

If the project also has an E2E test command, append an E2E instruction to the Tester context:
```
E2E target: {_ephemeral_url}
Run E2E tests against this URL: {_cmd_e2e}
```

**Browser scenario execution instructions.** If the item has
unsatisfied browser QA requirements (`browser_smoke` or
`browser_diff`), append browser execution instructions to the Tester
prompt. Read browser requirements via the registered
`qa.requirement.list` surface — `yoke qa requirement list --item
"YOK-${_id}"` — and filter the result rows to `qa_kind IN
('browser_smoke','browser_diff')`.

```bash
_browser_reqs=$(yoke qa browser-context get --item "${_id}" \
  --project "${_project}" --json \
  | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['result']['requirements']))")
```

If `_browser_reqs` is non-empty AND `_ephemeral_url` is not `"none"` and not `"pending"`, append this block to the Tester prompt:

```
## Browser Scenario Execution

This item has browser QA requirements that must be executed against the ephemeral environment.
Ephemeral URL: {_ephemeral_url}

**You MUST execute browser scenarios using the canonical orchestrator**:
```
yoke qa browser run \
 --item {_id} --project {_project} --base-url {_ephemeral_url}
```

The orchestrator will:
1. Fetch browser_smoke / browser_diff scenarios via qa.browser_context.get
2. Validate the ephemeral URL is reachable
3. Start the browser daemon if needed
4. Execute each scenario step via the machine-local browser daemon
5. Save screenshots to scratch-backed QA artifact storage
6. Record qa_run with executor_type='browser_substrate' and qa_artifact
   rows through qa.run.add / qa.run.complete / qa.artifact.add

**Before running the orchestrator**, you may refine the scenario
steps. Read the current scenarios via `yoke qa browser-context get
--item {_id} --project {_project} --json` (the
`result.requirements[*].success_policy` payloads carry the scenario
steps). To refine a
scenario (update steps, add assertions, fix routes), use executor
vocabulary:
- Actions: navigate, click, fill_form, assert, screenshot, wait_for,
  scroll, hover, select
- Fields: route (not url), target (not selector), capture: true on
  screenshot steps

Persist the refined scenario back to the requirement via the
`qa.requirement.update` function call (envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)):
`target = {kind: "qa_requirement", qa_requirement_id:
<requirement_id>}`, `payload = {success_policy: <refined_json>}`.
The handler updates the requirement row atomically; never issue a raw
UPDATE against `qa_requirements` from skill prose.

**After the orchestrator completes:**
- Exit 0 = all scenarios passed. Include the JSON summary in your report.
- Exit 1 = one or more scenarios failed. Report the failures. This does NOT automatically
 fail your overall verdict — use your judgement based on the failure nature.
- Exit 2 = operator env setup failure (URL unreachable, auto-bootstrap failed).
 **HARD STOP** — immediately fail your verdict with a clear message:
 "FAIL — browser QA blocked by operator environment issue (exit 2). Auto-bootstrap
 failed — escalate to operator."
 Do NOT continue testing other ACs — the environment must be fixed first.

Browser evidence is written directly to qa_runs. Both your
review verdict AND the orchestrator's qa_runs must exist for the item to advance.
```

If `_browser_reqs` is non-empty but `_ephemeral_url` is `"none"` or `"pending"`, append a warning instead:
```
## Browser QA Notice

This item has browser QA requirements (browser_smoke/browser_diff) but no ephemeral
URL is available ({_ephemeral_url}). Browser scenarios cannot be executed.
The item will not be able to advance past the QA gate without browser evidence.
```

#### E5. Update to Stopped After Tester

After the Tester returns (in the post-Tester processing, after step 5n), update the ephemeral environment status to `stopped`:

```bash
# Only if _env_id was set (ephemeral env was created in E1)
if [ -n "${_env_id}" ]; then
 yoke ephemeral-env update "${_env_id}" status "stopped"
fi
```

This is performed regardless of the Tester verdict (PASS or FAIL). The ephemeral environment is a per-dispatch resource and should be cleaned up after each test cycle.

**Note on retry:** If the item fails and is retried (Engineer re-dispatch), E1 will create a new env record (or upsert the existing one via `ON CONFLICT(project, branch) DO UPDATE`) on the next dispatch cycle.

---
