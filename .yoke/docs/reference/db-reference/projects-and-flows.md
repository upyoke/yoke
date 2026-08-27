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
id TEXT PRIMARY KEY -- short slug (e.g., 'yoke', 'external-webapp')
name TEXT NOT NULL -- display name
emoji TEXT DEFAULT '' -- project emoji (e.g., '🐂', '🧩'); shown in BOARD.md title
github_repo TEXT -- GitHub repo in owner/repo format (e.g., 'example-org/external-webapp')
default_branch TEXT DEFAULT 'main'
github_sync_mode TEXT NOT NULL DEFAULT 'disabled' -- 'enabled' | 'disabled'; legacy NULL/empty values normalize to disabled
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
```

**Per-project GitHub sync switch** — new projects start `disabled`, which keeps the project's backlog DB-only: every backlog→GitHub issue sync surface skips the project (logged skip, not an auth failure), `yoke resync` excludes it from fetch/classification/repair, and explicit issue-creating operations refuse. Reader: `yoke_core.domain.projects_github_sync_mode`; flip via `yoke projects update ... --github-sync-mode <mode>`. Enabling requires an active verified private App binding unless `--allow-public-github-sync` is explicit. Dry-run or normalize legacy/empty modes with `yoke projects github-sync-mode repair [--apply]`. The verified App binding is outbound repository authority; `github_repo` is its compatibility display projection. Full semantics and safe repository-rebinding order live in [github-sync.md](../github-sync.md).

**Project-level deployment-flow default** — read the project default via `yoke project-structure deploy-defaults get --project <project>` or, from Python, `yoke_core.domain.deploy_defaults.get_default_flow(project_id)`. Entries live in `project_structure` with `family='deploy_defaults'`, `attachment_value='project'`, payload `{"deployment_flow": "<flow-id>"}`. Absence is a valid state; callers treat it as "no project default" and fall back to inference.

**Project-level context routing** — read the project-wide always-included docs and per-topic doc lists via `python3 -m yoke_core.domain.context_routing get-always <project>`, `... get-topic <project> <topic>`, and `... list-topics <project>`. From Python: `yoke_core.domain.context_routing.{get_always_docs, get_topic_docs, list_topics, get_topic_map}`. Entries live in `project_structure` with `family='context_routing'`, `attachment_value='project'`, `entry_key='always'` for the project-wide set or any other topic name for topic-keyed sets, payload `{"docs": ["<repo-relative-path>", ...]}`. Absence is a valid state; consumers treat missing entries as "no routing configured for that key" and fall back to discovery heuristics.

**Project-level hosting posture** — read what the project decided about who runs its hosting via `yoke project-structure get --project <project> --family hosting_posture --json`. Entries live in `project_structure` with `family='hosting_posture'`, `attachment_value='project'`, payload `{"posture": "aws-admin" | "no-yoke-managed-host", "provider": "<optional prose>", "note": "<optional prose>"}`. `aws-admin` means Yoke manages hosting on AWS through the capability of that name; `no-yoke-managed-host` means the operator runs the hosting and Yoke applies no infrastructure, asks for no hosting credential, and proposes no infra Packs. `provider` and `note` are operator prose recording where the code actually runs — never acted on. Absence is a valid state meaning the question is still open, so onboarding asks it once rather than assuming AWS; the undecided state is never written as a row. Vocabulary: `yoke_contracts.hosting_posture`.

Seed data: a fresh universe seeds no project rows — projects enter through
onboarding (`yoke projects create` / `yoke project install`). QA plan
attachments declare which project checks run at each workflow transition.

### Deployment Flow Defaulting Rules

Items receive a `deployment_flow` via a two-tiered enforcement model:

**Auto-default at idea time:**
- Read the project's `deploy_defaults` entry via `yoke project-structure deploy-defaults get --project <project>` first. Empty get omits `--deployment-flow` and falls back to context inference. Never store the literal `none`.
- Merge-only or `-internal` defaults attach so Usher Route A stays automatic.
- A persistent default (`target_tier=persistent` / has a target environment) is not applied to clearly non-delivery work (docs, research) or when hosting is not healthy (unresolved/empty target environment), unless the operator or title is deploy work.
- The Yoke control-plane project's configured default is `yoke-internal` (operator-authored `deploy_defaults`, not a seed).

**Hard enforcement at planning gate:**
- Shepherd `planning_to_plan_drafted` transition blocks if `deployment_flow` is NULL on an epic
- Epic tasks are excluded (they inherit from their parent epic's flow)
- Operator must explicitly choose a flow before the item can reach `planned`
- `HC-missing-flow` doctor check surfaces items missing flows at WARN severity

Branch-triggered auto-deploy behaviour (the `{branch: flow_id}` trigger map that once lived on `projects`) is not a live truth source in Yoke. Actions runners and similar substrates may still perform deploys, but Yoke chooses which flow runs for which work item or run. If future branch-level guardrails (for example, "this branch is allowed to deploy production") become necessary, they will land as explicit policy rather than as branch-triggered flow selection.

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
- Coherence: per-request `BEGIN IMMEDIATE` transaction; mutation history flows through the shared event ledger.

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
`reviewing-implementation` transition seeds a blocking `implementation_review`
requirement where `registered-command-quick` would have attached, and
registering a command for any scope — the `command-ci` runner included — is
refused by name. Vocabulary: `yoke_contracts.verification_posture`.

Path-attached operating context lives in `path_context_values` (per-target, keyed by family) under the path-context substrate. Project Structure contains only the project-level families listed above.

Project Structure has no placeholder or named-only family slots. The `family-list` CLI prints only the live family vocabulary and grammar metadata.

**Read/write surface:**

```sh
python3 -m yoke_core.cli.db_router project-structure get <project-id> [--family F]
python3 -m yoke_core.cli.db_router project-structure patch <project-id> --stdin
python3 -m yoke_core.cli.db_router project-structure seed <project-id>
python3 -m yoke_core.cli.db_router project-structure family-list
```

The same commands are available through the service-client CLI as `project-structure-get`, `project-structure-patch`, and `project-structure-seed`. The write surface takes a single imperative op list with `ops`; see `yoke_core.domain.project_structure` for the full contract.

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

Capabilities enabled per project (e.g., SSH access, Docker support). Declares what a project can do. Non-sensitive settings are in the `settings` column; DB-backed secrets are stored separately in `capability_secrets`, while machine-local secret material lives under `~/.yoke/secrets/capability-secrets`. `settings` + the capability secret resolver are the canonical storage path; `config` is compatibility storage and should not receive new secrets.

```sql
id INTEGER PRIMARY KEY
project TEXT NOT NULL REFERENCES projects(id)
type TEXT NOT NULL -- capability type (e.g., 'ssh', 'docker', 'ephemeral-env')
config TEXT NOT NULL -- compatibility JSON with settings + secrets mixed
settings TEXT DEFAULT '{}' -- JSON: non-sensitive capability settings only
verified_at TEXT -- last verification timestamp (NULL = unverified)
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
UNIQUE(project, type) -- one capability instance per type per project
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
project TEXT NOT NULL REFERENCES projects(id)
type TEXT NOT NULL -- capability type (e.g., 'github')
key TEXT NOT NULL -- secret key name (e.g., 'token')
value TEXT NOT NULL DEFAULT '' -- the imported secret value
source TEXT NOT NULL DEFAULT 'literal' CHECK(source = 'literal')
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
UNIQUE(project, type, key) -- one secret per key per capability per project
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
project TEXT NOT NULL REFERENCES projects(id)
name TEXT NOT NULL -- display name (e.g., 'Prod Release')
description TEXT
stages TEXT NOT NULL -- → JSONB on Postgres; JSON array of stage objects [{name, step_runner, ...}]
on_failure TEXT DEFAULT 'halt' -- failure policy: 'halt' stops the pipeline
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
target_tier TEXT -- persistent | ephemeral | NULL (merge-only)
target_environment_id INTEGER -- internal REFERENCES environments(id); required exactly when target_tier='persistent'
done_description TEXT DEFAULT NULL -- per-flow "done means..." contract; human-readable definition of what "done" means for this flow
status TEXT NOT NULL DEFAULT 'active' -- 'active' accepts assignments/runs; 'disabled' is history-only
UNIQUE(project, name)
```

Every stage object requires `name` (string) and `step_runner` (string, closed set). Valid step runner types: `auto`, `health-check`, `warm-up`, `environment-activate`, `core-container-deploy`, `ephemeral-deploy`, `ephemeral-teardown`, `ephemeral-verify`, `human-approval`, `github-actions-workflow`. A database is brought up to its code by the boot converge that starts the container, so applying a migration is not a deployment stage and there is no stage `kind` vocabulary.

**`github-actions-workflow` step runner:** Triggers a GitHub Actions workflow and polls for completion. Stage fields: `workflow` (workflow filename, e.g., `deploy.yml`), `watch_for` (state to wait for, e.g., `"completed"`), `on_failure` (`"halt"`). Used by external projects where GitHub Actions owns the pipeline. Python owners: `yoke_core.domain.github_actions` + `yoke_core.domain.deploy_pipeline`.

**`warm-up` step runner:** Issues one heavy relayed function call against the
environment the run just rolled, so the pipeline pays the server cold start
(engine imports, connection pool, caches) instead of whoever calls first — a
cold start can outlast the client's relay ceiling and fail at the caller while
the box is healthy. Stage fields: `connection_env` (required; the client
connection that serves the rolled environment), `function` (defaults to
`board.data.get`, a read that exercises the whole server path and needs no
arguments), and `timeout_s` (defaults to 180). The stage passes only when the
call answers, and records the function, connection, and measured latency on
the run as `DeploymentRunWarmedUp`; a failure fails the stage with the real
transport or function error rather than marking a cold box deployed. Python
owner: `yoke_core.domain.deploy_warm_up`.

**`health-check` step runner:** An explicit stage `url` is checked verbatim (plain HTTP 2xx, no request-id contract assumed for arbitrary endpoints). When the stage omits `url`, the URL resolves from the flow's referenced environment settings as `https://{hosts.api}{health_path}` and the check enforces the Yoke core x-request-id echo contract: the request carries a generated `x-request-id` header and fails unless the response echoes the exact same value back.

Read the current project workflow definition with `yoke workflows definition get --project <slug> --json`; inspect a flow with `yoke deployment-flows get <flow-id>` / `stages`.

Flows are ordinary control-plane rows, managed by command like every other
database object. Define one with
`yoke deployment-flows create <flow-id> --project <slug> --name NAME --stages-file PATH`,
adding `--target-tier persistent --environment <name>` for a flow that deploys
to a registered environment or `--target-tier ephemeral` for per-run preview
substrate. Change lifecycle state with
`yoke deployment-flows set-status <flow-id> active|disabled`; disabling is how a
route is retired — it prevents new assignments and runs while preserving the
definition and every historical run. A definition referenced by a run is
immutable, so changing a route's shape is a retirement plus a new flow. The
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
