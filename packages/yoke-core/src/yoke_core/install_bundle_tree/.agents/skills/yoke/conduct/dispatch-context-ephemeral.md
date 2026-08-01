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
delivery model. Use the worktree's actual branch, not an assumed `PREFIX-N`
filename; epic lanes may have distinct branch names.

```bash
yoke ephemeral-env create "${_project}" "${_worktree_branch}" --item "PREFIX-${_id}" --json
```

The record is created with `status=pending` (the default). Store `_env_id` for use in subsequent steps. The status transitions to `starting` only after a workflow run is found.

#### E2. Trigger the Declared Delivery Model

Resolve the immutable code identity before triggering either delivery model:

```bash
_expected_browser_branch="${_worktree_branch}"
_expected_browser_sha=$(git -C "${_worktree_path}" rev-parse HEAD)
```

The same branch and SHA must identify the deployed build and every Browser
case invocation later in E4. Branch on the validated policy's `trigger`; no
project-slug branch is allowed.

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
   PREFIX-<id> --project <project> --flow <flow_id> --target-env ephemeral
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

**Browser case execution instructions.** Read the materialized requirements
with `yoke qa requirement list --item "PREFIX-${_id}" --json`. If it contains an
unsatisfied, non-waived case whose `method_id` is `browser-check` or
`browser-inspection`, append Browser execution instructions to the Tester
prompt. Method identity, not `qa_kind` or item metadata, selects this path.

If Browser method cases exist AND `_ephemeral_url` is not `"none"` and not
`"pending"`, append this block to the Tester prompt:

```
## Browser Scenario Execution

This item has Browser method cases that must be executed against the ephemeral environment.
Ephemeral URL: {_ephemeral_url}
Expected branch: {_expected_browser_branch}
Expected HEAD SHA: {_expected_browser_sha}

**Execute each materialized case with the shared case runner**:
```
yoke qa case run \
  --requirement-id <requirement-id> \
  --base-url "{_ephemeral_url}" \
  --expected-branch "{_expected_browser_branch}" \
  --expected-sha "{_expected_browser_sha}"
```

The runner validates reachability and freshness, starts the Browser substrate,
executes only the named case, records the run, and stores its evidence. A
`browser-check` returns an automatic pass/fail. A `browser-inspection` creates
a review request after capture and remains unresolved until that request is
approved, rejected, or the requirement is waived. Do not add a second run
manually, do not rewrite the materialized case snapshot, and do not omit the
expected branch or SHA from any case invocation.
```

If Browser method cases exist but `_ephemeral_url` is `"none"` or `"pending"`,
append a warning instead:
```
## Browser QA Notice

This item has Browser method cases but no ephemeral URL is available
({_ephemeral_url}). The cases cannot execute, so the transition remains
blocked until the environment is available.
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
