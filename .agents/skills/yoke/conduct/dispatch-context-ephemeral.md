# Dispatch Context — Ephemeral Environment Lifecycle

Extracted from `dispatch-context-gates.md`. Contains the full
ephemeral environment sub-step (5f-project-ephemeral) and browser QA execution.

---

## 5f-project-ephemeral. Ephemeral Environment Lifecycle (shared sub-step)

This sub-step runs for any non-empty project that carries the
`ephemeral-env` capability. It manages the full lifecycle of an ephemeral
environment for the item's branch: create the DB record, trigger the workflow,
poll for readiness, inject the URL into the Tester prompt, and tear down after
testing. It is independent of whether the separate `5f-project` context block
is needed.

**Boundary:** lifecycle reads and writes use the registered `yoke
ephemeral-env get/create/update` wrappers. Read the project's policy through
`yoke projects capability-settings get --project <project> --cap-type
ephemeral-env --json`; `result.settings_json` declares `trigger`,
`preview_domain`, and, for flow-triggered projects, `flow_id`. GitHub-triggered
projects use the registered `yoke github-actions ...` family. Flow-triggered
projects use the registered deployment-run composer plus the retained
owner-only deployment executor.

**Prerequisite:** The item's project must have the `ephemeral-env`
capability. Dispatch the `projects.capability.has` function call
(envelope in
[`../idea/body-and-sync-functions.md`](../idea/body-and-sync-functions.md)):
`target = {kind: "global"}`, `payload = {project: "${_project}",
cap_type: "ephemeral-env"}`. Read `response.result.has` — when
`false`, skip this sub-step entirely and emit a visible warning so the operator
notices the missing capability. This prevents silent browser QA gaps without
special-casing a project slug.

For `trigger=github-push`, also read the `github` capability through the same
registered settings-get wrapper and form `<repo_owner>/<repo_name>`. Resolve
the workflow's current project path from `.yoke/packs.json`: use the
`ephemeral-environments` Pack file identity ending in `-ephemeral.yml`, then
read that entry's `path`. This is why a project that moves a Pack-installed
workflow must apply `yoke packs relink`: Conduct follows the receipt instead
of guessing the old filename. If the binding, Pack receipt, or recorded
workflow path is missing, surface the exact missing authority and skip the
preview; never guess from the project slug.

#### E1. Create Environment Record

Create the ephemeral environment DB record **before** triggering either
delivery model. Use the worktree's actual branch, not an assumed `YOK-N`
filename; epic lanes may have distinct branch names.

```bash
yoke ephemeral-env create "${_project}" "${_worktree_branch}" --item "YOK-${_id}" --json
```

The record is created with `status=pending` (the default). Store `_env_id` for use in subsequent steps. The status transitions to `starting` only after a workflow run is found.

#### E2. Trigger the Declared Delivery Model

Branch on the validated policy's `trigger`; no project-slug branch is allowed.

For `github-push`:

1. Push the actual worktree branch from `_worktree_path` to `origin` so the
   latest Engineer commit is the deploy subject.
2. Resolve the exact HEAD SHA and the current workflow path from the Pack
   receipt.
3. Find the matching run with `yoke github-actions find-run <owner/repo>
   <workflow-path> <head-sha> --project <project> --json`.
4. Record its run id and `status=starting` through `yoke ephemeral-env update`.
5. Wait with `yoke github-actions wait-run ... --timeout 1800 --project
   <project> --json`.

For `flow`:

1. Require the policy's `flow_id`; capability validation rejects a flow
   trigger without one.
2. Compose the item-bound run with `yoke deployment-runs start-for-item
   YOK-<id> --project <project> --flow <flow_id> --target-env ephemeral
   --json` and record its run id plus `status=starting` on the environment.
3. Read `yoke status --json`. Use the selected connection's owner-only
   `<connection>-db-admin` sibling only if it appears in `connection.envs`;
   never store that machine-local profile name in project settings.
4. Execute `yoke --env <connection>-db-admin deployment-runs execute <run-id>
   --product-repo-path <worktree-path>`. The generic `ephemeral-deploy`
   executor reads the source project's policy and project-owned Pack files,
   while `host_project` supplies the environment and provider authority.

Any trigger, lookup, wait, or execution failure updates `status=failed`, sets
the Tester-facing URL to `none`, and continues without browser QA only when no
browser requirement demands it. Do not silently fall back from one trigger
model to the other.

#### E3. Read the Result

After either delivery model completes, read `yoke ephemeral-env get <project>
<branch> --json`. The flow executor has already recorded its URL and deployed
SHA. For a successful GitHub-triggered run, derive the URL from the canonical
branch slug and policy `preview_domain`, then write `url` and `status=healthy`
through `yoke ephemeral-env update`. Set `_ephemeral_url` from the final read,
not from an old project file or a hard-coded domain.

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
