# Sites, environments and deployment flows

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Deployments](../index.md) > Sites, environments and flows
<!-- /yoke:breadcrumbs -->

Read the site, environment and flow records that define deployment targets and pipeline execution.

## Table: sites

Deployment targets for projects. A site represents a deployable unit (e.g., a web app, API service).

```sql
id INTEGER PRIMARY KEY -- internal surrogate key; never an operator input
project_id INTEGER NOT NULL REFERENCES projects(id)
name TEXT NOT NULL -- sole human identifier, unique within the project
description TEXT -- human-readable description
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" in Related
settings TEXT DEFAULT '{}' -- structured site configuration
UNIQUE(project_id, name)
```

Seed data: none — a fresh universe seeds no sites; rows are registered through `projects.site.create` (`yoke projects site create`, idempotent already_present) when the first work that deploys needs one, with settings maintained through the projects settings surfaces.

## Table: environments

Deployment environments for sites (e.g., prod, stage). `local` is a machine-config client concept, not a deploy-target environments row.

```sql
id INTEGER PRIMARY KEY -- internal surrogate key; never an operator input
site INTEGER NOT NULL
project_id INTEGER NOT NULL REFERENCES projects(id)
name TEXT NOT NULL -- sole human identifier, unique within the project
url TEXT -- public URL (e.g., 'http://100.115.178.33:3000')
deploy_method TEXT -- e.g., 'github-actions', 'rsync+docker'
deploy_command TEXT -- shell command to run for deployment
health_check_url TEXT -- URL to check after deployment
config_notes TEXT -- human-readable notes about the environment
last_deployed_at TEXT -- stamped on successful run completion and on release_pin.record
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" in Related
settings TEXT DEFAULT '{}' -- structured environment configuration
UNIQUE(project_id, name)
FOREIGN KEY(site, project_id) REFERENCES sites(id, project_id)
```

Seed data: a fresh universe seeds no sites or environments — onboarding registers rows via `projects.site.create` / `projects.environment.create` (idempotent already_present) only when the first work deploys, with structured settings maintained through the projects settings surfaces. The operator's own registry rows (sites, environments, capability settings) live in the operator's private ops repo and are applied by operator tooling.

## Table: deployment_flows

Deployment flow definitions. Each flow defines an ordered sequence of stages that an item passes through after merge.

```sql
id TEXT PRIMARY KEY -- e.g., 'project-prod-release'
project_id INTEGER NOT NULL REFERENCES projects(id)
name TEXT NOT NULL -- display name (e.g., 'Prod Release')
description TEXT
stages TEXT NOT NULL -- → JSONB on Postgres; JSON array of stage objects [{name, step_runner, ...}]
on_failure TEXT DEFAULT 'halt' -- failure policy: 'halt' stops the pipeline
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" in Related
target_tier TEXT -- persistent | ephemeral | NULL (merge-only)
target_environment_id INTEGER -- internal REFERENCES environments(id); required exactly when target_tier='persistent'
done_description TEXT DEFAULT NULL -- per-flow "done means..." contract; human-readable definition of what "done" means for this flow
status TEXT NOT NULL DEFAULT 'active' -- 'active' or 'disabled'
definition_schema_version INTEGER NOT NULL DEFAULT 1 -- stage vocabulary only
takes_delivery_custody INTEGER NOT NULL DEFAULT 0 -- 1 takes delivery of carried items
supersedes_flow_id TEXT REFERENCES deployment_flows(id)
UNIQUE(project_id, name)
```

Every stage object requires `name` (string) and `step_runner` (string, closed set). Valid step runner types: `auto`, `health-check`, `warm-up`, `environment-activate`, `core-container-deploy`, `ephemeral-deploy`, `ephemeral-teardown`, `ephemeral-verify`, `human-approval`, `github-actions-workflow`, `qa`. A database is brought up to its code by the boot converge that starts the container, so applying a migration is not a deployment stage and there is no stage `kind` vocabulary.

Every stage declares its runner fields at the top level, beside `name` and `step_runner`; a stage carrying a nested `config` object is refused on write, because the pipeline builds a stage's runner config from the stage itself and nested fields would never reach the runner. Normalization for execution keeps the stage the definition declared, so `target`, `stage_kind`, and `scope` are readable by the receipt layer and the preview producer. Python owner: `yoke_core.domain.flow_validation`.

Definition schema v2 adds release-policy configuration without changing the
schema-v1 executor: every v2 stage declares `stage_kind` (`execution` or `qa`)
and scope. QA stages use `step_runner: "qa"`, target a persistent environment
or an earlier preview, may select reusable QA cases, and declare verdict
authority separately from informational notification. The current source runtime executes v2. Validate against the serving runtime
before activation. Schema support and supported QA target kinds are separate
admission checks; a schema floor does not promise an unsupported target.
Delivery custody is `takes_delivery_custody`, not a side effect of that
version: a v2 flow can take none, and adding `stage_kind` changes no
enrollment. Create accepts `--takes-delivery-custody true|false`; omitting it
stores `true` for schema version 2 or later and `false` for version 1.

**`human-approval`:** the driver asks the serving control plane to evaluate the
exact run/stage through `deployment_runs.stage_approval.evaluate` (`yoke
deployment-runs stage-approval evaluate RUN-ID --stage STAGE`). Evaluation raises
the declared decision request and reports its wait; it never approves. Candidate
code must not derive policy from a deployed database's different schema.
`deployment_runs.approve` records the authorized answer. Approval wakes the
run's live driver, or the project's steering seat when none is attached, with
same-run re-entry commands; the runner alone advances state. Rejection closes
the run. Owners: `deployment_approval_requests`, `handlers.deployment_stage_approval`,
`deployment_stage_approval_dispatch`, `deployment_stage_decision_effect`, reached
through `decision_request_subject_effect` in `yoke_core.domain`.

**`github-actions-workflow` step runner:** Triggers a GitHub Actions workflow and polls for completion. Stage fields: `workflow` (workflow filename, e.g., `deploy.yml`), `watch_for` (state to wait for, e.g., `"completed"`), `on_failure` (`"halt"`). Used by external projects where GitHub Actions owns the pipeline. Python owners: `yoke_core.domain.github_actions` + `yoke_core.domain.deploy_pipeline`.

A workflow stage normally dispatches its `ref` branch (default `main`), whose
workflow source may differ from `{head_sha}` checkout inputs after the branch
moves. For builds requiring workflow/ref/checkout to be one attested commit,
set `run_from_release_commit: true`. The boolean applies only to workflow stages
and excludes `ref`. `github_actions.dispatch_tag.ensure` creates or confirms the
lightweight `yoke-deploy/<run-id>` tag at the release commit, then dispatches it.
Tags are retained and create-only: another existing SHA refuses with
`dispatch_tag_conflict`; an unavailable commit with `dispatch_tag_commit_missing`.
Re-drive uses the same tag. Exclude `yoke-deploy/` from tag-push workflow triggers.
Owners: `deploy_pipeline_release_commit_ref`, `handlers.github_actions_dispatch_tag`.

`input_bindings` can bind workflow input names to registered project branches,
e.g. `{"consumer_sha": {"project": "other", "branch": "main"}}`. Run start resolves
each once into `deployment_runs.bound_sources`; unreachable branches refuse and
conflicting branches for one project refuse. Stages substitute stored commits.
Start enrollment admits the bound project's delivery-ready items as ordinary
members; delivery is judged against that exact recorded commit.
Each project record's `outputs` stores only commits actually produced by the
run, e.g. `{"commit_sha": "...", "reason": "release_pin_materialization"}`; other
unowned commits remain outside-Yoke changes. Hosted `promotion_receipts` retain
verified attempt artifacts; served-identity QA uses the artifact's deployed SHA,
including no-op pins, without re-resolving a branch. Owners:
`deployment_run_bound_sources`, `deployment_run_project_sources`,
`deployment_run_release_output`, `deployment_run_release_output_record`.

**`warm-up`:** makes one heavy relayed call against the rolled environment.
Required `connection_env` names its client connection; `function` defaults to
read-only `board.data.get`; `timeout_s` defaults to 180. Pass requires an actual
answer. `DeploymentRunWarmedUp` records function, connection and latency;
transport/function failure fails the stage. Owner: `yoke_core.domain.deploy_warm_up`.

**`health-check` step runner:** An explicit stage `url` is checked verbatim (plain HTTP 2xx, no request-id contract assumed for arbitrary endpoints). When the stage omits `url`, the URL resolves from the flow's referenced environment settings as the declared `hosts.api` URL plus `health_path` and the check enforces the Yoke core x-request-id echo contract: the request carries a generated `x-request-id` header and fails unless the response echoes the exact same value back.

Read the current project workflow definition with `yoke workflows definition get --project <slug> --json`; inspect a flow with `yoke deployment-flows get <flow-id>` / `stages`.

Flows are ordinary control-plane rows, managed by command like every other
database object. Define one with
`yoke deployment-flows create <flow-id> --project <slug> --name NAME --stages-file PATH`
(`[--takes-delivery-custody true|false]`),
adding `--target-tier persistent --environment <name>` for a flow that deploys
to a registered environment or `--target-tier ephemeral` for per-run preview
substrate. Validate advanced configuration with `yoke deployment-flows validate`,
replace any unused definition atomically with `deployment-flows update`, reorder
its complete stage set with `deployment-flows reorder`, or publish the successor
to a used definition with `deployment-flows version`. Change lifecycle state with
`yoke deployment-flows set-status <flow-id> active|disabled`; disabling is how a
route is retired — it prevents new assignments and runs while preserving the
definition and every historical run. A definition referenced by a run is
immutable except for its lifecycle status, so changing its configuration
requires a new version linked by `supersedes_flow_id`. The
project default lives in the `deploy_defaults` Project Structure family: read it
with `yoke project-structure deploy-defaults get --project <slug>` and set it
through `yoke project-structure patch apply`.

Schema initialization creates the registry but never seeds a project's delivery
topology, and no file in a project repository defines it either. Every
project—without exception—owns its flow IDs, stage names, workflow filenames,
retirements, and default as control-plane rows. Runtime behavior comes from
stored stages and capabilities, not from a recognized project slug or flow-ID
prefix.

Flow ids are definitions, not executions. Item-bound delivery creates concrete `run-...` ids through `/yoke usher`, and the run retains its definition relationship for durable history.

## Related

- [Projects](../../databases/model/projects.md)
- [Timestamp discipline](../../databases/migrations.md#timestamp-discipline)
