# Conduct — ephemeral QA target

Use actual project capability, independently of project-context injection.
Read help before capability/delivery mutation; never branch by project slug.

```text
yoke projects capability has --project {PROJECT} --cap-type ephemeral-env
yoke projects capability-settings get --project {PROJECT} --cap-type ephemeral-env --json
```

Absent capability skips with a visible warning. settings_json owns trigger,
preview_domain and required flow_id for flow. github-push also reads github
capability repo_owner/repo_name. Resolve current workflow path from the
ephemeral-environments Pack receipt entry ending -ephemeral.yml. Missing Pack,
binding or path names its repair/relink; no guessed workflow or silent fallback.
Missing target still blocks any Browser requirement that demands it.

## E1–E3. Create, deliver, verify

Create pending record before either trigger, once per actual branch/dispatch
cycle. Retain returned env_id:

```text
yoke ephemeral-env create {PROJECT} {BRANCH} --item PREFIX-N --json
git -C {WORKTREE_PATH} rev-parse HEAD
```

Record expected branch and exact current Engineer commit. They must identify
both the deployed build and every subsequent Browser case. github-push uses
the declared verified publishing surface, never a worker handpush; find/wait the
matching current Pack workflow and SHA through registered GitHub Actions:

```text
yoke github-actions find-run {OWNER_REPO} {WORKFLOW_PATH} {HEAD_SHA} --project {PROJECT} --json
yoke github-actions wait-run {OWNER_REPO} {RUN_ID} --timeout 1800 --project {PROJECT} --json
```

Store actual run id and starting only once found. Flow trigger requires its
validated flow_id; hold DEPLOY:<run-owning project> before composition/execution
and release after settlement. A mandate forbidding worker run creation routes
this preview request to covering steering, not a self-authorized exception.
An authorized driver uses the declared composer and transport:

```text
yoke deployment-runs start-for-item PREFIX-N --project {PROJECT} --flow {FLOW_ID} --environment ephemeral --json
yoke --env {CONNECTION} deployment-runs execute {RUN_ID} --product-repo-path {WORKTREE_PATH}
```

Continue the same running handle to exit. HTTPS is ordinary authority; serving
API self-deploy refusal names control-plane operator recovery. Source policy and
Pack own runner; host_project owns configured environment/provider authority.
Do not substitute a different trigger or credentials.

Trigger/lookup/wait/execute failure records failed and URL=none. Continue other
work only when no blocking Browser case requires the target; otherwise HALT for
repair/operator waiver. After success read the exact environment again. Flow
records URL/deployed SHA; GitHub success derives URL from canonical branch slug
and preview_domain, then updates URL/healthy through registered env update.
Tester receives final readback, never an old project file/domain.

## E4. Refresh Browser context

Overwrite the pre-preparation URL in the context block; include configured E2E
target/command where present. Read actual materialized methods. Unsatisfied,
nonwaived browser-check/browser-inspection selects this path, not qa_kind.
With healthy URL, supply branch/SHA and the exact shared case runner:

```text
yoke qa case run --requirement-id {requirement_id} --base-url {URL} --expected-branch {BRANCH} --expected-sha {HEAD_SHA}
```

Runner verifies reachability/freshness and records capture. Browser-check gives
automatic result; Browser-inspection remains unresolved pending independent
acceptance/rejection or authorized waiver. No duplicate manual run, rewritten
case snapshot, omitted identity or capture-as-pass. None/pending URL prints
the unmet Browser obligation and keeps transition blocked.

## E5. Stop each dispatch resource

After Tester reflections/artifacts, on PASS or FAIL, update only the env_id
created for this dispatch:

```text
yoke ephemeral-env update {env_id} status stopped
```

Retry prepares a fresh/upserted record and candidate; do not reuse stopped
resource state or skip lifecycle because the branch was seen previously.
