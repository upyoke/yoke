# DB Reference — Projects, Sites, Capabilities, Flows
Schemas for the project registry, the Project Structure aggregate, sites/environments, capabilities/secrets/templates, and deployment-flow definitions. Cross-link back from [db-reference.md](../db-reference.md) for entry points, the domain catalog, timestamp discipline, JSON-payload conventions, qa CLI, body write path, and the status lifecycle reference.

## Table: projects
Registered projects that Yoke can manage. The `projects` table holds only
shared identity and repo metadata; machine-local checkout paths live in
machine config. Per-project structure and routing declarations live in the
Project Structure aggregate. Executable verification lives in project QA
plans.
Every registered slug uses the same project commands and capability resolution. A project name never unlocks behavior: specialized delivery comes from that project's capability rows, environments, and workflow definitions. Checkout-local or direct-module recipes are valid only when their surface explicitly declares a source-dev/admin boundary.

```sql
id INTEGER PRIMARY KEY -- internal project identity
slug TEXT NOT NULL -- public project slug
public_item_prefix TEXT NOT NULL -- project public-ref prefix
retired_at TEXT -- null while active
name TEXT NOT NULL -- display name
emoji TEXT DEFAULT '' -- project emoji (e.g., '🐂', '🧩'); shown in BOARD.md title; obeys the glyph contract (session-level-routing.md)
github_repo TEXT -- GitHub repo in owner/repo format (e.g., 'example-org/external-webapp')
default_branch TEXT DEFAULT 'main'
github_sync_mode TEXT NOT NULL DEFAULT 'disabled' -- 'enabled' | 'disabled'; legacy NULL/empty values normalize to disabled
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
```

**GitHub sync:** new projects are DB-only (`disabled`); skips precede authentication.
Explicit issue creation refuses and resync excludes disabled projects. Enable
only with a verified private App binding or explicit public-sync permission.
The binding owns outbound repository authority; `github_repo` is display only.
Read [GitHub sync](../github-sync.md) before changing mode or rebinding; it owns
repair, disabled semantics and the sync-off-first ordering.

**Project-level deployment-flow default** — read the project default via `yoke project-structure deploy-defaults get --project <project>` or, from Python, `yoke_core.domain.deploy_defaults.get_default_flow(project_id)`. Entries live in `project_structure` with `family='deploy_defaults'`, `attachment_value='project'`, payload `{"deployment_flow": "<flow-id>"}`. Absence is a valid state; callers treat it as "no project default" and fall back to inference.

**Context routing:** read `yoke project-structure get --project P --family context_routing --json`.
Project-attached keyed entries store `{"docs": ["<repo-relative-path>", ...]}`;
reserved `entry_key="always"` is always-included, other keys are topics. Missing
entries mean no routing for that key, with ordinary discovery remaining.
Internal accessors belong to `yoke_core.domain.context_routing`.

**Project-level hosting posture** — read what the project decided about who runs its hosting via `yoke project-structure get --project <project> --family hosting_posture --json`. Entries live in `project_structure` with `family='hosting_posture'`, `attachment_value='project'`, payload `{"posture": "aws-admin" | "no-yoke-managed-host", "provider": "<optional prose>", "note": "<optional prose>"}`. `aws-admin` means Yoke manages hosting on AWS through the capability of that name; `no-yoke-managed-host` means the operator runs the hosting and Yoke applies no infrastructure, asks for no hosting credential, and proposes no infra Packs. `provider` and `note` are operator prose recording where the code actually runs — never acted on. Absence is a valid state meaning the question is still open, so onboarding asks it once rather than assuming AWS; the undecided state is never written as a row. Vocabulary: `yoke_contracts.hosting_posture`.
Seed data: a fresh universe seeds no project rows — projects enter through
onboarding (`yoke projects create` / `yoke project install`). QA plan
attachments declare which project checks run at each workflow transition.

### Deployment Flow Defaulting Rules
Items receive a `deployment_flow` via a two-tiered enforcement model:

**Auto-default at idea time:**
- Resolve explicit item flow, else the project's per-workflow default (`yoke workflows mechanics get` / `yoke workflows delivery-default set --project P --workflow W --flow F`), else `yoke project-structure deploy-defaults get --project <project>`. Empty omits `--deployment-flow`. Never store the literal `none`.
- Task stays exempt even if an old `workflow_defaults` mapping still names a flow.
- Classify a candidate with `yoke deployment-flows get FLOW` (`target_tier` empty is merge-only; `persistent` is a persistent default). Never classify by an id suffix.
- Omitting `--deployment-flow` inherits the project/workflow default at later resolution; it does not waive delivery or make the item merge-only. A docs/process title is not a merge-only exemption.
- An explicit merge-only request selects a registered merge-only definition (`target_tier` empty) via `yoke deployment-flows list`.
- A failed lookup or unsupported definition is reported; do not swallow it with `|| true`.
- Do not assign a disabled flow, or a definition whose `yoke deployment-flows validate ... --status active` reports `execution_supported=false`.
- Intake screenshot/approval requests persist as item QA rows (`qa.requirement.add`, placed by [Where a Browser case runs](../browser-scenarios.md#where-a-browser-case-runs)). Pre-merge gates do not wait for that environment. Explicit "have me approve it" is `required_human` on the requested environment's item-QA stage. They do not rewrite shared defaults, and they never `update-stages` a shared, referenced, or immutable flow.
- The Yoke control-plane project's configured default is `yoke-internal` (operator-authored `deploy_defaults`, not a seed).

**Hard enforcement at planning gate:**
- Shepherd's binding-derived final review edge blocks if `deployment_flow` is NULL on an epic
- Epic tasks are excluded (they inherit from their parent epic's flow)
- Operator must explicitly choose a flow before the item can reach `planned`
- `HC-missing-flow` doctor check surfaces items missing flows at WARN severity
Stored item/run flows select delivery. A project branch-trigger map is not a flow authority.

## Project Structure aggregate
The Project Structure aggregate coexists with `projects` as the unversioned declaration of project-wide policy/family structure. It lives in a single table:

```
project_structure   -- family entries with identity
                       (project_id, family, attachment_value, entry_key)
```

**Envelope grammar (frozen):**
- Attachment branches: `project` (sentinel), `path_selector` (kind ∈ {`exact`, `glob`, `tree`}).
- Multiplicity: `singleton` or `keyed_set`.
- Identity: `(project_id, family, attachment_value)` for singleton, `(project_id, family, attachment_value, entry_key)` for keyed_set.
- Coherence: one atomic caller-owned transaction (Postgres `BEGIN`); mutation history flows through the shared event ledger.

**Families (fully instantiated):**
`architecture_model`, `areas`, `context_routing`, `deploy_defaults`,
`hosting_posture`, `integration_targets`, `mappings`, `ownership_defaults`,
`test_roots`, `verification_posture`, `verification_profiles`.
`deploy_defaults`, `architecture_model`, `hosting_posture`, and
`verification_posture` are project-attached singletons.
`context_routing` is a project-attached keyed set whose payload is
`{"docs": [str, ...]}` and whose reserved `entry_key="always"` denotes the
project-wide always-included set.
`verification_profiles` is **descriptive, not executable**. Its
`test_command` payload records what a project's verification is for a human
reader; no gate reads it. The command the `reviewing-implementation` gate
actually runs is the project's registered QA plan case, bound with:

```sh
yoke qa registered-command set --project P --scope quick --command "<argv>"
```
Writing `verification_profiles.test_command` and stopping there leaves the
project with no gate command at all.

**Project-level verification posture** — read whether a project has attested
it has no suite to bind via `yoke project-structure get --project <project>
--family verification_posture --json`. Entries live in `project_structure`
with `family='verification_posture'`, `attachment_value='project'`, payload
`{"posture": "attested-no-tests", "reason": "<required prose>"}`. The reason
is required: it is what makes the row an attestation rather than an omission,
and it is what a reviewer reads at the gate to learn why no command ran. Only
that one posture is stored — a project that *has* a command already says so
through its `registered-command-*` plan, and a second spelling of that fact
could only drift from it — so absence means no attestation. Write it with
`yoke qa no-tests attest --project P --reason "..."`, which also retires any
`registered-command-*` plan the project held, and remove it with `yoke qa
no-tests clear --project P --reason "..."`. While it stands, the
workflows consuming project defaults seed a blocking `no_tests_declared`
requirement where `registered-command-quick` would have attached. Its agent
run is labeled `agent-attested / no-tests-declared`, not as executed tests, and
registering a command for any scope — the `command-ci` runner included — is
refused by name. Vocabulary: `yoke_contracts.verification_posture`.
Path-attached operating context lives in `path_context_values`, per target and family. It is distinct from Project Structure entries and their attachment grammar.
Project Structure admits only its declared family vocabulary and grammar.

**Registered read/write surface:**

```sh
yoke project-structure get --project P --family F --json
yoke project-structure patch apply --project P --ops-json '[{"op": "put", "family": "deploy_defaults", "attachment": "project", "payload": {"deployment_flow": "FLOW"}}]' --json
```
Read command help for payloads. `project_structure.patch.apply` validates the
imperative `ops` batch before applying it atomically. Family/attachment grammar
lives in `yoke_core.domain.project_structure`; internal seed/module clients
are contributor tooling, not agent mutation APIs.

## Table: sites

Deployment targets for projects. A site represents a deployable unit (e.g., a web app, API service).

```sql
id INTEGER PRIMARY KEY -- internal surrogate key; never an operator input
project_id INTEGER NOT NULL REFERENCES projects(id)
name TEXT NOT NULL -- sole human identifier, unique within the project
description TEXT -- human-readable description
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
settings TEXT DEFAULT '{}' -- structured site configuration
UNIQUE(project_id, name)
```

Seed data: none — a fresh universe seeds no sites; rows are registered through `projects.site.create` (`yoke projects site create`, idempotent already_present) during onboarding, with settings maintained through the projects settings surfaces.

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
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
settings TEXT DEFAULT '{}' -- structured environment configuration
UNIQUE(project_id, name)
FOREIGN KEY(site, project_id) REFERENCES sites(id, project_id)
```

Seed data: a fresh universe seeds no sites or environments — projects enter through onboarding, registering rows via `projects.site.create` / `projects.environment.create` (idempotent already_present), with structured settings maintained through the projects settings surfaces. The operator's own registry rows (sites, environments, capability settings) live in the operator's private ops repo and are applied by operator tooling.

## Table: project_capabilities

Capabilities enabled per project (e.g., SSH access, Docker support). Declares what a project can do. Non-sensitive settings are in the `settings` column; DB-backed secrets are stored separately in `capability_secrets`, while machine-local secret material lives under `~/.yoke/secrets/capability-secrets`. `settings` + the capability secret resolver are the canonical storage path; capability settings contain no secret values.

```sql
id INTEGER PRIMARY KEY
project_id INTEGER NOT NULL REFERENCES projects(id)
type TEXT NOT NULL -- capability type (e.g., 'ssh', 'docker', 'ephemeral-env')
settings TEXT DEFAULT '{}' -- JSON: non-sensitive capability settings only
verified_at TEXT -- last verification timestamp (NULL = unverified)
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
UNIQUE(project_id, type) -- one capability instance per type per project
```

Seed data: none — capability rows are configured per project during onboarding (only project-agnostic capability *templates* are seeded; see Table: capability_templates).

## Table: capability_secrets

Per-key DB secret storage for project capabilities. Separates sensitive values
that Yoke core must hold from non-sensitive settings. DB-backed writes store imported literal values in
`capability_secrets`; `source` is always `literal`. `aws-admin` secrets and
`ssh.private_key` are not stored here: they live on the local machine under
`~/.yoke/secrets/capability-secrets/<project>/<capability>/<key>`.

```sql
id INTEGER PRIMARY KEY
project_id INTEGER NOT NULL REFERENCES projects(id)
type TEXT NOT NULL -- capability type (e.g., 'github')
key TEXT NOT NULL -- secret key name (e.g., 'token')
value TEXT NOT NULL DEFAULT '' -- the imported secret value
source TEXT NOT NULL DEFAULT 'literal' CHECK(source = 'literal')
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
UNIQUE(project_id, type, key) -- one secret per key per capability per project
```

Access DB-backed secrets through the project capability resolver. The same
resolver derives local `aws-admin` and `ssh.private_key` file paths from project
slug, capability, and key; callers such as `aws_capability_env` do not read
ambient shell credentials.

## Table: capability_templates

Defines available capability types with their validation schemas, descriptions, and dependency chains. The `required_config` field is a JSON array of objects describing each config key, including whether it contains secrets. The `requires` field declares capability prerequisites (e.g., `ephemeral-env` requires `docker`). The `secret` flag in `required_config` entries routes values to `settings` or `capability_secrets`.

```sql
id TEXT PRIMARY KEY -- capability type slug (e.g., 'ssh', 'docker', 'ephemeral-env')
name TEXT NOT NULL -- display name
description TEXT -- human-readable description
required_config TEXT NOT NULL -- JSON array: [{key, description, secret}]
requires TEXT DEFAULT '[]' -- JSON array of prerequisite capability IDs
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
```

Seed data: generic capability templates are converged during schema initialization:
- `ssh` -- SSH access to a remote server (settings: user, host, key_path; local-only secret: private_key)
- `docker` -- Docker daemon accessible for container operations (keys: host)
- `ephemeral-env` -- Per-branch preview policy. `trigger=github-push` uses the project's Pack-installed workflow; `trigger=flow` requires a project-owned `flow_id`. Host project/environment, preview domain/namespace, port ranges, and cleanup lifetime are explicit non-secret settings.
- `aws-admin` -- AWS credentials with broad admin access (keys: access_key_id [secret], secret_access_key [secret], region)
- `aws-route53` -- DNS management via Route53 (keys: hosted_zone_id; requires: aws-admin)
- `github` -- GitHub App repo binding metadata for issue sync, PRs, Actions, and API access (keys: repo_owner, repo_name, installation_id, repository_id). The verified GitHub deployment API base is stored on `project_github_repo_bindings.api_url` and `github_app_installations.api_url`, not inferred from the repo slug. GitHub App private-key and webhook secret material belongs to the control-plane secret store, not `capability_secrets`.
- `test_environment` -- uv extras, groups, and nested project path that lane prepare and the test wrappers install and run (keys: uv_project, uv_extras, uv_groups). Test trees stay on Project Structure `test_roots`.

Deployment SSH credentials belong to the separate `ssh` capability. The
`github` capability has no secret fields; GitHub App private keys and webhook
secrets stay in the control-plane secret store.

## Table: deployment_flows

Deployment flow definitions. Each flow defines an ordered sequence of stages that an item passes through after merge.

```sql
id TEXT PRIMARY KEY -- e.g., 'project-prod-release'
project_id INTEGER NOT NULL REFERENCES projects(id)
name TEXT NOT NULL -- display name (e.g., 'Prod Release')
description TEXT
stages TEXT NOT NULL -- → JSONB on Postgres; JSON array of stage objects [{name, step_runner, ...}]
on_failure TEXT DEFAULT 'halt' -- failure policy: 'halt' stops the pipeline
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
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
project's deploy-lock driver, or its steering seat when no holder exists, with
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
