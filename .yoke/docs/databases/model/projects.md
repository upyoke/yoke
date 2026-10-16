# Projects and capabilities

<!-- yoke:breadcrumbs -->
[Yoke](../../index.md) > [Databases](../index.md) > Projects and capabilities
<!-- /yoke:breadcrumbs -->

Read schemas for the project registry, Project Structure aggregate, capabilities,
secrets and templates. Cross-link back from [reference.md](../reference.md) for entry points, the domain catalog, timestamp discipline, JSON-payload conventions, qa CLI, body write path, and the status lifecycle reference.

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
emoji TEXT DEFAULT '' -- project emoji (e.g., '🐂', '🧩'); shown in BOARD.md title; obeys the glyph contract (../../agents/level-launches.md#glyph-contract)
github_repo TEXT -- GitHub repo in owner/repo format (e.g., 'example-org/external-webapp')
default_branch TEXT DEFAULT 'main'
github_sync_mode TEXT NOT NULL DEFAULT 'disabled' -- 'enabled' | 'disabled'; legacy NULL/empty values normalize to disabled
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see "Timestamp discipline" below
```

**GitHub sync:** new projects are DB-only (`disabled`); skips precede authentication.
Explicit issue creation refuses and resync excludes disabled projects. Enable
only with a verified private App binding or explicit public-sync permission.
The binding owns outbound repository authority; `github_repo` is display only.
Read [GitHub sync](../../github/sync.md) before changing mode or rebinding; it owns
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
- Intake screenshot/approval requests persist as item QA rows (`qa.requirement.add`, placed by [Where a Browser case runs](../../reference/browser-scenarios.md#where-a-browser-case-runs)). Pre-merge gates do not wait for that environment. Explicit "have me approve it" is `required_human` on the requested environment's item-QA stage. They do not rewrite shared defaults, and they never `update-stages` a shared, referenced, or immutable flow.
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

## Related

- [Flows](../../deployments/model/flows.md)
