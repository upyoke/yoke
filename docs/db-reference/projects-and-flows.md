# DB Reference — Projects, Sites, Capabilities, Flows

Schemas for the project registry, the Project Structure aggregate, sites/environments, capabilities/secrets/templates, and deployment-flow definitions. Cross-link back from [db-reference.md](../db-reference.md) for entry points, the domain catalog, timestamp discipline, JSON-payload conventions, qa CLI, body write path, and the status lifecycle reference.

## Table: projects

Registered projects that Yoke can manage. The `projects` table holds only shared identity and repo metadata; machine-local checkout paths live in machine config. Per-project structured settings (test commands, deployment-flow default, merge verification policy, context routing) live in the Project Structure aggregate (see below).

```sql
id TEXT PRIMARY KEY -- short slug (e.g., 'yoke', 'buzz')
name TEXT NOT NULL -- display name
emoji TEXT DEFAULT '' -- project emoji (e.g., '🐂', '🐝'); shown in BOARD.md title
github_repo TEXT -- GitHub repo in owner/repo format (e.g., 'example-org/buzz')
default_branch TEXT DEFAULT 'main'
github_sync_mode TEXT -- 'enabled' | 'backlog_only'; new rows use backlog_only, legacy NULL resolves enabled
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
```

**Per-project GitHub sync switch** — new projects start `backlog_only`, which keeps the project's backlog DB-only: every backlog→GitHub issue sync surface skips the project (logged skip, not an auth failure), `yoke resync` excludes it from fetch/classification/repair, and explicit issue-creating operations refuse. Reader: `yoke_core.domain.projects_github_sync_mode`; flip via `yoke projects update ... --github-sync-mode <mode>`. Enabling requires an active verified App binding. Dry-run or normalize legacy effective-enabled rows with `yoke projects github-sync-mode repair [--apply]`. The verified App binding is outbound repository authority; `github_repo` is its compatibility display projection. Full semantics and safe repository-rebinding order live in [github-sync.md](../github-sync.md).

**Project-level test commands** — read the `quick`, `full`, `e2e`, and `smoke` scopes via `python3 -m yoke_core.domain.command_definitions get <project> <scope>` or, from Python, `yoke_core.domain.command_definitions.list_commands(project_id)`. Entries live in `project_structure` with `family='command_definitions'` and `attachment_value='project'`. An absent or empty entry means "no command defined" for that scope.

**Project-level deployment-flow default** — read the project default via `yoke project-structure deploy-defaults get --project <project>` or, from Python, `yoke_core.domain.deploy_defaults.get_default_flow(project_id)`. Entries live in `project_structure` with `family='deploy_defaults'`, `attachment_value='project'`, payload `{"deployment_flow": "<flow-id>"}`. Absence is a valid state; callers treat it as "no project default" and fall back to inference.

**Project-level merge verification policy** — read the project's pre-merge verification policy via `python3 -m yoke_core.domain.merge_verification get <project>` or, from Python, `yoke_core.domain.merge_verification.get_policy(project_id)`. Entries live in `project_structure` with `family='merge_verification'`, `attachment_value='project'`, payload `{"command": "<shell command>", "timeout_seconds": <positive integer>}`. Absence is a valid state; the merge engine emits an explicit `[phase:tests] no merge policy configured for project '<id>' — skipping project tests` log line and runs nothing in that case. The merge engine reads this family alone — it never falls back to `command_definitions.{quick, full, e2e, smoke}`. The four agent-facing scopes in `command_definitions` describe the project's test suites for Tester/Engineer dispatch and doctor health checks; `merge_verification` is the merge gate, isolated from agent test selection by construction. Set explicitly via `python3 -m yoke_core.domain.merge_verification set <project> "<command>" --timeout-seconds <seconds>`; command and timeout are both project policy.

**Project-level context routing** — read the project-wide always-included docs and per-topic doc lists via `python3 -m yoke_core.domain.context_routing get-always <project>`, `... get-topic <project> <topic>`, and `... list-topics <project>`. From Python: `yoke_core.domain.context_routing.{get_always_docs, get_topic_docs, list_topics, get_topic_map}`. Entries live in `project_structure` with `family='context_routing'`, `attachment_value='project'`, `entry_key='always'` for the project-wide set or any other topic name for topic-keyed sets, payload `{"docs": ["<repo-relative-path>", ...]}`. Absence is a valid state; consumers treat missing entries as "no routing configured for that key" and fall back to discovery heuristics.

Seed data: a fresh universe seeds no project rows — projects enter through onboarding (`yoke projects create` / `yoke project install`). `merge_verification` is optional for all projects; projects without that family entry skip merge-time project tests until an operator records an explicit merge policy.

### Deployment Flow Defaulting Rules

Items receive a `deployment_flow` via a two-tiered enforcement model:

**Auto-default at idea time:**
- Read the project's `deploy_defaults` entry via `yoke project-structure deploy-defaults get --project <project>`; when present, use its flow automatically.
- The Yoke control-plane project's configured default is `yoke-internal` (operator-authored `deploy_defaults`, not a seed).
- External projects use their configured `deploy_defaults` entry, or fall back to context inference when none is set.

**Hard enforcement at planning gate:**
- Shepherd `planning_to_plan_drafted` transition blocks if `deployment_flow` is NULL on an epic
- Epic tasks are excluded (they inherit from their parent epic's flow)
- Operator must explicitly choose a flow before the item can reach `planned`
- `HC-missing-flow` doctor check surfaces items missing flows at WARN severity

Branch-triggered auto-deploy behaviour (the `{branch: flow_id}` trigger map that once lived on `projects`) is not a live truth source in Yoke. Actions runners and similar substrates may still perform deploys, but Yoke chooses which flow runs for which ticket/run. If future branch-level guardrails (for example, "this branch is allowed to deploy production") become necessary, they will land as explicit policy rather than as branch-triggered flow selection.

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

`areas`, `mappings`, `test_roots`, `verification_profiles`, `ownership_defaults`, `integration_targets`, `command_definitions`, `deploy_defaults`, `merge_verification`, `context_routing`.

`command_definitions` is keyed by scope (`quick`, `full`, `e2e`, `smoke`); `deploy_defaults` and `merge_verification` are project-attached singletons; `context_routing` is a project-attached keyed_set whose payload is `{"docs": [str, ...]}` and whose reserved `entry_key="always"` denotes the project-wide always-included set (any other `entry_key` is a topic name).

Path-attached operating context lives in `path_context_values` (per-target, keyed by family) under the path-context substrate. Project Structure contains only the project-level families listed above.

Project Structure has no placeholder or named-only family slots. The `family-list` CLI prints only the live family vocabulary and grammar metadata.

**Read/write surface:**

```sh
python3 -m yoke_core.cli.db_router project-structure get <project-id> [--family F]
python3 -m yoke_core.cli.db_router project-structure patch <project-id> --stdin
python3 -m yoke_core.cli.db_router project-structure seed <project-id>
python3 -m yoke_core.cli.db_router project-structure family-list
```

The same commands are available through the service-client CLI as `project-structure-get`, `project-structure-patch`, and `project-structure-seed`. The write surface takes a single imperative op list with `ops`; see `runtime/api/domain/project_structure.py` for the full contract.

## Table: sites

Deployment targets for projects. A site represents a deployable unit (e.g., a web app, API service).

```sql
id TEXT PRIMARY KEY -- e.g., 'buzz-web'
project TEXT NOT NULL REFERENCES projects(id)
name TEXT NOT NULL -- display name
description TEXT -- human-readable description
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
```

Seed data: none — a fresh universe seeds no sites; rows are written through the projects settings surfaces during onboarding.

## Table: environments

Deployment environments for sites (e.g., production, staging). `local` is a machine-config client concept, not a deploy-target environments row.

```sql
id TEXT PRIMARY KEY -- e.g., 'buzz-web-production'
site TEXT NOT NULL REFERENCES sites(id)
name TEXT NOT NULL -- environment name (e.g., 'production', 'prod', 'stage')
url TEXT -- public URL (e.g., 'http://100.115.178.33:3000')
deploy_method TEXT -- e.g., 'github-actions', 'rsync+docker'
deploy_command TEXT -- shell command to run for deployment
health_check_url TEXT -- URL to check after deployment
config_notes TEXT -- human-readable notes about the environment
last_deployed_at TEXT -- last successful deployment timestamp
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
UNIQUE(site, name) -- one environment per name per site
```

Seed data: a fresh universe seeds no sites or environments — projects enter through onboarding, and their sites/environments carry structured settings written through the projects settings surfaces. The operator's own registry rows (sites, environments, capability settings) live in the operator's private ops repo and are applied by operator tooling.

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

Seed data: 6 templates seeded by `python3 -m yoke_core.cli.db_router projects init`:
- `ssh` -- SSH access to a remote server (settings: user, host, key_path; local-only secret: private_key)
- `docker` -- Docker daemon accessible for container operations (keys: host)
- `ephemeral-env` -- Per-branch ephemeral environments (keys: web_base_port, api_base_port, compose_file, env_file, startup_timeout_s; requires: docker)
- `aws-admin` -- AWS credentials with broad admin access (keys: access_key_id [secret], secret_access_key [secret], region)
- `aws-route53` -- DNS management via Route53 (keys: hosted_zone_id; requires: aws-admin)
- `github` -- GitHub App repo binding metadata for issue sync, PRs, Actions, and API access (keys: repo_owner, repo_name, installation_id, repository_id). The verified GitHub deployment API base is stored on `project_github_repo_bindings.api_url` and `github_app_installations.api_url`, not inferred from the repo slug. GitHub App private-key and webhook secret material belongs to the control-plane secret store, not `capability_secrets`.

**Bootstrap config field:** The `github` capability may include an `ssh_key_path` secret pointing to the SSH private key used by the bootstrap script to configure GitHub Secrets for deployment workflows.

## Table: deployment_flows

Deployment flow definitions. Each flow defines an ordered sequence of stages that an item passes through after merge.

```sql
id TEXT PRIMARY KEY -- e.g., 'buzz-prod-release'
project TEXT NOT NULL REFERENCES projects(id)
name TEXT NOT NULL -- display name (e.g., 'Prod Release')
description TEXT
stages TEXT NOT NULL -- → JSONB on Postgres; JSON array of stage objects [{name, executor, ...}]
on_failure TEXT DEFAULT 'halt' -- failure policy: 'halt' stops the pipeline
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
target_env TEXT DEFAULT NULL -- target deployment environment; auto-sets deployed_to on pipeline completion
done_description TEXT DEFAULT NULL -- per-flow "done means..." contract; human-readable definition of what "done" means for this flow
UNIQUE(project, name)
```

Stage objects come in two shapes. Executor-shaped stages require `name` (string) and `executor` (string, closed set). Valid executor types: `auto`, `health-check`, `environment-activate`, `core-container-deploy`, `ephemeral-deploy`, `ephemeral-teardown`, `ephemeral-verify`, `human-approval`, `github-actions-workflow`. Kind-shaped stages carry `kind` instead (`migration_apply` is the only kind; fields `model_name` + `lifecycle_phase`, optional `name`) and bind the project's governed migration contract into the flow. The pipeline derives the stage name from the kind (`migration_apply` → `migration-apply`; an explicit `name` wins) for `deployment_runs.current_stage`, `--from-stage` resume, and stage telemetry — live flow rows need no `name` key. Dispatch (`yoke_core.domain.deploy_pipeline_migration`) verifies per member item the same evidence gate the lifecycle enforces at `implementing → reviewing-implementation` (completed `migration_audit` rows written only by the governed runner; `{"state":"none"}` claims and item-less runs pass with an explicit stage-result note on `DeploymentRunStageCompleted`); the governed apply itself (rehearse → lease → backup → live-apply) never runs inside the pipeline.

**`github-actions-workflow` executor type:** Triggers a GitHub Actions workflow and polls for completion. Stage fields: `workflow` (workflow filename, e.g., `deploy.yml`), `watch_for` (state to wait for, e.g., `"completed"`), `on_failure` (`"halt"`). Used by external projects where GitHub Actions owns the pipeline. Python owners: `yoke_core.domain.github_actions` + `yoke_core.domain.deploy_pipeline`.

**`health-check` executor type:** An explicit stage `url` is checked verbatim (plain HTTP 2xx, no request-id contract assumed for arbitrary endpoints). When the stage omits `url`, the URL resolves from the flow's `target_env` environment settings as `https://{hosts.api}{health_path}` and the check enforces the Yoke core x-request-id echo contract: the request carries a generated `x-request-id` header and fails unless the response echoes the exact same value back.

Flows are managed via `python3 -m yoke_core.domain.flow` (`init`, `create`, `get`, `list`, `stages`, `delete`; also routed as `python3 -m yoke_core.cli.db_router flows <subcmd>`). `flow delete <id> [--repoint-items-to <flow-id>]` removes a flow; it refuses while items still reference the flow unless `--repoint-items-to` retargets them.

Seed data: `python3 -m yoke_core.cli.db_router flows init` seeds flow definitions only for projects already present in the universe (a fresh universe gets none). The definitions:
- `yoke-internal` — Script/doc changes, no deployment: `migration_apply (primary, implementing) -> merged (auto) -> complete (auto)` (no target_env, done="Merged to main")
- `yoke-prod-release` — Yoke core container to prod: `migration_apply (primary, implementing) -> merged (auto) -> env-activate (environment-activate) -> core-deploy (core-container-deploy) -> health-check (health-check) -> complete (auto)` (target_env=prod, done="Yoke core container deployed to prod and public health check passed")
- `yoke-stage-release` — Yoke core container to stage, same as prod minus the migration stage (stage data is throwaway): `merged (auto) -> env-activate (environment-activate) -> core-deploy (core-container-deploy) -> health-check (health-check) -> complete (auto)` (target_env=stage, done="Yoke core container deployed to stage and public health check passed")
- `yoke-ephemeral-deploy` — Branch/SHA Yoke core preview environment: `merged (auto) -> ephemeral-deploy (ephemeral-deploy) -> complete (auto)` (target_env=ephemeral, done="Yoke core preview environment deployed")
- `buzz-prod-release` — v1 production deploy with smoke test: `start (auto) -> prod-deploy (github-actions-workflow, buzz-deploy.yml) -> smoke (github-actions-workflow, buzz-smoke.yml) -> complete (auto)` (4 stages, target_env=production, done="Deployed to production and smoke checks passed"). No staging stages — Buzz v1 has no staging environment.
- `buzz-prod-hotfix` — Direct to production with smoke test (4 stages, target_env=production, done="Hotfix deployed to production")
- `buzz-internal` — Doc or config change, no deployment (2 auto stages, no target_env, done="Merged to main")

`yoke-prod-release` and `yoke-stage-release` are flow ids, not run ids. Operator-attended Yoke environment redeploys can be item-less: create a deployment run from the flow, then execute the printed `run-...` id through the deploy watcher. The deploy-owner project is the project that owns the environment and flow rows and may differ from the Yoke product project after re-parenting; the explicit product checkout supplies the deploy code, build context, and release SHA. These command-shaped surfaces use the `<control-plane-env>-db-admin` local-Postgres admin profile only for source-dev/admin or audited break-glass runs; routine reads and product workflows stay on HTTPS/API-backed `yoke ...` wrappers or `yoke db read`. Today `<control-plane-env>` is `prod` for Yoke deployment-run metadata.

```bash
target_env=<target-env>
target_branch=<main-or-stage>
source_checkout=<source-checkout>
deploy_owner_project=<deploy-owner-project>
git -C "$source_checkout" fetch origin "$target_branch"
git -C "$source_checkout" checkout --detach FETCH_HEAD
YOKE_ENV=<control-plane-env>-db-admin python3 -m yoke_core.cli.db_router runs create-run "$deploy_owner_project" "yoke-${target_env}-release" --target-env "$target_env" --created-by operator
YOKE_ENV=<control-plane-env>-db-admin YOKE_GITHUB_ACTIONS_RELAY_ENV=<hosted-control-plane-env> python3 -m yoke_core.tools.watch_deploy --product-src "$source_checkout" -- {run-id}
```

Do not turn the `YOKE_ENV=<env>-db-admin` shape into a normal retry hint after a product read or domain wrapper fails. Use the domain wrapper/HTTPS path for normal access, and reserve direct local-Postgres authority for the admin redeploy path above or the break-glass runbook. Every retry or `--from-stage` resume of an item-less run must repeat the same `--product-src` argument. The watcher validates that checkout and derives the registry's canonical 12-character image tag from its exact `HEAD`; a legacy explicit `--image-tag` is accepted only when it resolves to that same commit and is canonicalized before dispatch.

The hosted relay selector is mandatory for normal deploys. Only the attended
bootstrap that introduces or repairs the relay may replace it with
`YOKE_GITHUB_ACTIONS_LOCAL_AUTHORITY=1`.
