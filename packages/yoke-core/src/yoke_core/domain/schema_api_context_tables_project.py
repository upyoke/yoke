"""``project`` topic table entries for the schema cheat sheet.

Sibling of :mod:`schema_api_context_tables` (which combines per-topic
dicts into the canonical ``CANONICAL_TABLES``). Holds the ``project``
topic entries: sites, environments, project_structure, deployment_flows, deployment_runs,
deployment_run_items, ephemeral_environments, path_snapshots, project_capabilities,
capability_secrets, migration_audit.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


PROJECT_TABLES: dict[str, dict] = {
    "projects": {
        "columns": [
            ("id", "INTEGER"),
            ("org_id", "INTEGER"),
            ("slug", "TEXT"),
            ("name", "TEXT"),
            ("emoji", "TEXT"),
            ("default_branch", "TEXT"),
            ("github_repo", "TEXT"),
            ("public_item_prefix", "TEXT"),
            ("breakage_policy", "TEXT"),
            ("github_sync_mode", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Project registry. The human-readable label column is `name` "
            "— there is NO `display_name` column (stale guess). `id` is "
            "the project authority; `slug` is unique inside one `org_id` "
            "and resolves through the actor-visible project set or an org "
            "filter. `public_item_prefix` is the ticket prefix (`YOK`, "
            "`BUZ`). Canonical agent read: "
            "`yoke projects list` / "
            "`yoke projects get --project <slug>`; "
            "breakage_policy reader is "
            "yoke_core.domain.projects_breakage_policy. "
            "`github_sync_mode` is the per-project GitHub sync switch "
            "(enabled | backlog_only; new projects default backlog_only; "
            "legacy NULL = enabled); reader is "
            "yoke_core.domain.projects_github_sync_mode, flip via "
            "`yoke projects update ... --github-sync-mode <mode>`. "
            "Enabling requires an active verified App binding. Find or "
            "normalize unsafe legacy rows with `yoke projects "
            "github-sync-mode repair [--apply]`. "
            "backlog_only turns off every backlog->GitHub issue sync "
            "surface for the project — the logged skip line is policy, "
            "not an auth failure. "
            "Project-scoped settings do NOT live on a `projects.settings` "
            "column; use `project_structure`, `project_capabilities.settings`, "
            "or environment settings surfaces for those aggregates. "
            "Source-dev/admin database connector setup uses `yoke dev "
            "db-admin setup <deploy-env> --control-plane-env "
            "<https-connection> --yes`; it reads `current_database()` through "
            "that exact named HTTPS connection's `db.read.run` tenant route. "
            "The deploy environment still owns stack, region, endpoint, and "
            "secret ARN. Never substitute the declared deploy database, "
            "active connection, a local admin env, or a deploy DSN for the "
            "HTTPS control-plane database identity."
        ),
    },
    "sites": {
        "columns": [
            ("id", "TEXT"),
            ("name", "TEXT"),
            ("description", "TEXT"),
            ("created_at", "TEXT"),
            ("settings", "TEXT"),
            ("project_id", "INTEGER"),
        ],
        "notes": (
            "Deployable sites belong to projects through numeric "
            "`sites.project_id = projects.id`. Environment ownership is "
            "indirect: join `environments.site = sites.id`, then join the "
            "site to its project. Structured site configuration lives in "
            "the JSON `settings` column."
        ),
    },
    "environments": {
        "columns": [
            ("id", "TEXT"),
            ("site", "TEXT"),
            ("name", "TEXT"),
            ("url", "TEXT"),
            ("deploy_method", "TEXT"),
            ("deploy_command", "TEXT"),
            ("health_check_url", "TEXT"),
            ("config_notes", "TEXT"),
            ("last_deployed_at", "TEXT"),
            ("created_at", "TEXT"),
            ("settings", "TEXT"),
        ],
        "notes": (
            "Named deployment environments belong to a site through the "
            "TEXT `site` column. There is NO `project_id` column on this "
            "table (stale guess). Resolve project ownership with "
            "`environments.site = sites.id` and "
            "`sites.project_id = projects.id`. Deployment metadata such as "
            "git branch, hosts, database, and Pulumi settings lives in the "
            "JSON `settings` column. Agent reads use `yoke projects "
            "environment-settings get --project <slug> --environment-id "
            "<id> --path <scalar.path>`; the registered function requires "
            "explicit scalar paths and returns a `values` projection. The "
            "wrong aggregate-response guess is `settings_json`: neither "
            "get nor merge returns the settings document. Merge returns "
            "only `changed_paths` plus its message. The local-only "
            "`environment-merge-settings` domain command cannot reach an "
            "HTTPS authority."
        ),
    },
    "project_structure": {
        "columns": [
            ("id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("family", "TEXT"),
            ("attachment_value", "TEXT"),
            ("attachment_kind", "TEXT"),
            ("entry_key", "TEXT"),
            ("payload", "TEXT"),
        ],
        "notes": (
            "Aggregate for project-scoped settings. Families include "
            "command_definitions (test commands per scope), "
            "context_routing (per-topic doc paths), and deploy_defaults "
            "(default deployment_flow). Read through the family-specific "
            "domain helpers (e.g. command_definitions, context_routing); "
            "there is no top-level command_definitions or context_routing "
            "table — raw queries against those names fail."
        ),
    },
    "deployment_flows": {
        "columns": [
            ("id", "TEXT"),
            ("project_id", "INTEGER"),
            ("name", "TEXT"),
            ("description", "TEXT"),
            ("stages", "TEXT"),
            ("on_failure", "TEXT"),
            ("created_at", "TEXT"),
            ("target_env", "TEXT"),
            ("done_description", "TEXT"),
            ("status", "TEXT"),
        ],
        "notes": (
            "Deployment-flow definitions keyed by TEXT `id`. Project "
            "lookup uses numeric `project_id`; join projects for the slug. "
            "The human flow name is `name`. `status` is `active` or "
            "`disabled`; disabled definitions remain readable for historical "
            "runs but cannot be assigned or start new runs. "
            "`stages` is a JSON-array column whose elements define the "
            "ordered pipeline steps. Canonical lookup: `SELECT id, "
            "stages FROM deployment_flows WHERE id = ?;` then "
            "`json.loads(stages)` to walk the stage list. If an SQL scalar "
            "read is truly needed, use Postgres JSONB operators such as "
            "`NULLIF(stages, '')::jsonb #>> '{0}'`."
        ),
    },
    "deployment_runs": {
        "columns": [
            ("id", "TEXT"),
            ("project_id", "INTEGER"),
            ("flow", "TEXT"),
            ("target_env", "TEXT"),
            ("release_lineage", "TEXT"),
            ("status", "TEXT"),
            ("current_stage", "TEXT"),
            ("created_at", "TEXT"),
            ("started_at", "TEXT"),
            ("completed_at", "TEXT"),
            ("created_by", "TEXT"),
        ],
        "notes": (
            "One row per deployment-flow execution. Primary key is the "
            "TEXT `id` (run identifier like 'run-YYYYMMDD-NNN'); the "
            "`flow` column joins to `deployment_flows.id`. There is no "
            "`item_id` column on this table. Item-bound delivery joins "
            "through `deployment_run_items`. Use `deployment_runs.id` in "
            "raw run queries; do not look for a `run_id` column on the run "
            "table (that column lives on `deployment_run_items`). Normal "
            "hosted releases are "
            "item-bound; zero-member runs are reserved for explicit "
            "environment administration and still advance this run row. To "
            "find the active deploy run for an item, JOIN through "
            "`deployment_run_items`: `SELECT dr.id, dr.status, "
            "dr.current_stage, dr.target_env FROM deployment_runs dr "
            "JOIN deployment_run_items dri ON dri.run_id = dr.id WHERE "
            "dri.item_id = ? ORDER BY dr.created_at DESC LIMIT 1;`. "
            "Stale-run HCs scan rows where `status` is non-terminal "
            "but `started_at` is older than the configured cutoff; "
            "item-less is suspicious only when a run never starts."
            " New run creation locks `deployment_runs` in Postgres, computes "
            "the UTC day's maximum numeric suffix plus one, and inserts under "
            "the same transaction with the primary key as a collision guard. "
            "`runs next-id` is only a non-reserving preview."
        ),
    },
    "deployment_run_items": {
        "columns": [
            ("run_id", "TEXT"),
            ("item_id", "INTEGER"),
            ("added_at", "TEXT"),
        ],
        "notes": (
            "Many-to-many linkage between deployment_runs and items. "
            "Composite primary key is `(run_id, item_id)`. Canonical "
            "JOINs: `dri.run_id = dr.id` reaches the parent run, "
            "`dri.item_id = items.id` reaches the linked item. See the "
            "deployment_runs entry above for the full active-run "
            "query. Do not require a row here for environment-level "
            "deploy runs; zero rows means no attached backlog item, not "
            "a broken run once `deployment_runs.status` has moved past "
            "`created`."
        ),
    },
    "ephemeral_environments": {
        "columns": [
            ("id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("branch", "TEXT"),
            ("item", "TEXT"),
            ("workflow_run_id", "TEXT"),
            ("github_ref", "TEXT"),
            ("port_api", "INTEGER"),
            ("port_web", "INTEGER"),
            ("url", "TEXT"),
            ("status", "TEXT"),
            ("started_at", "TEXT"),
            ("stopped_at", "TEXT"),
            ("health_check_url", "TEXT"),
            ("deployed_sha", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Branch/item-scoped ephemeral preview environment rows. "
            "Agent-facing lifecycle field writes use `yoke ephemeral-env "
            "update <env-id> <field> <value>` (`ephemeral_env.update`), "
            "not the retained domain-update command; the legacy domain helper still "
            "owns create/read/cleanup and cmd_update semantics. Conduct "
            "uses branch `YOK-{id}`."
        ),
    },
    "path_snapshots": {
        "columns": [
            ("id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("commit_sha", "TEXT"),
            ("built_at", "TEXT"),
        ],
        "notes": (
            "Path snapshot header keyed by `id`. Snapshot timestamp is "
            "`built_at`; there is NO `created_at` column on this table."
        ),
    },
    "project_capabilities": {
        "columns": [
            ("id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("type", "TEXT"),
            ("verified_at", "TEXT"),
            ("created_at", "TEXT"),
            ("settings", "TEXT"),
        ],
        "notes": (
            "Project capability rows keyed by `(project_id, type)`. The "
            "capability-name column is `type` (values include "
            "`github`, `docker`, `domain`, `migration_model`, and "
            "`github-actions-runner-fleet`); "
            "`settings` is a JSON blob carrying capability-specific "
            "configuration. The `github-actions-runner-fleet` network "
            "settings use `deployment_ssh_environments` for active VPS "
            "environment selectors and `deployment_ssh_stack_names` for "
            "explicit standalone VPS Pulumi stack references. The renderer "
            "merges and deduplicates them, binding environment stacks to "
            "`originElasticIpAddress` and standalone VPS stacks to "
            "`vpsElasticIpAddress`; neither output nor a literal address is "
            "guessed from the stack name. "
            "Canonical non-sensitive settings access is `yoke projects "
            "capability-settings get --project <slug> --cap-type <type>`. "
            "Full writes use the exact returned text with `capability-settings "
            "set ... --base <as-read-json>` (or `--new` for an absent row); "
            "single-path repairs use `capability-settings merge ... --set "
            "key.path=value`. These registered surfaces work over HTTPS, "
            "protect against lost updates, and run capability-specific typed "
            "canonicalization before mutation. Unknown fields on typed "
            "capabilities are refused so a mixed-version control plane cannot "
            "silently drop new authority fields. GitHub full-document settings "
            "remain binding-owned and are refused by the generic writer. The "
            "diagnostic all-capability SQL shape remains `SELECT type, settings "
            "FROM project_capabilities WHERE project_id = ?`; routine reads "
            "use the registered command instead. The Python workhorse is "
            "yoke_core.domain.projects_capabilities_settings; do not import "
            "settings helpers from projects_capabilities (wrong guess — that "
            "module owns capability listings and secrets). "
            "There are NO `project`, `capability_type`, `capability`, "
            "`key`, or `value` columns; those are stale guesses for this "
            "table."
        ),
    },
    "capability_secrets": {
        "columns": [
            ("id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("type", "TEXT"),
            ("key", "TEXT"),
            ("value", "TEXT"),
            ("source", "TEXT"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "Secret-value metadata for project capabilities. The "
            "capability discriminator column is `type`, not "
            "`capability_type`; keys such as `access_key_id`, "
            "`secret_access_key`, and other capability-defined names may appear "
            "in `key`. GitHub authentication does not read this table: project "
            "authority comes from `project_github_repo_bindings`, installation "
            "tokens are short-lived, and the App private key is control-plane-only. "
            "`aws-admin` secrets and `ssh.private_key` are machine-local files under "
            "`~/.yoke/secrets/capability-secrets/<project>/<capability>/` "
            "and should not be read from or written to this table. "
            "For DB-backed rows, `source` must be `literal`; file/env-backed "
            "secret rows are not a live storage shape. Resolve the project "
            "slug to `projects.id`, then query by `project_id`. Canonical "
            "lookup: "
            "`SELECT type, key, source FROM capability_secrets WHERE "
            "project_id = ? ORDER BY type, key;`. Do not print `value` in "
            "agent logs."
        ),
    },
    "migration_audit": {
        "columns": [
            ("id", "INTEGER"),
            ("migration_name", "TEXT"),
            ("description", "TEXT"),
            ("tables_declared", "TEXT"),
            ("expected_deltas", "TEXT"),
            ("pre_row_counts", "TEXT"),
            ("post_row_counts", "TEXT"),
            ("pre_fk_violations", "INTEGER"),
            ("post_fk_violations", "INTEGER"),
            ("backup_path", "TEXT"),
            ("state", "TEXT"),
            ("failure_reason", "TEXT"),
            ("exception_reason", "TEXT"),
            ("source_fingerprint", "TEXT"),
            ("rehearsed_at", "TEXT"),
            ("lease_id", "INTEGER"),
            ("test_copy_path", "TEXT"),
            ("baseline_verify_result", "TEXT"),
            ("author_verify_result", "TEXT"),
            ("session_id", "TEXT"),
            ("model_name", "TEXT"),
            ("project_id", "INTEGER"),
            ("started_at", "TEXT"),
            ("completed_at", "TEXT"),
            ("duration_ms", "INTEGER"),
            ("actor_id", "TEXT"),
            ("worktree", "TEXT"),
            ("source_branch", "TEXT"),
            ("source_commit", "TEXT"),
            ("integration_target", "TEXT"),
            ("change_class", "TEXT"),
        ],
        "notes": (
            "Governed migration audit rows. Lifecycle field is `state`; "
            "model attribution is `model_name`; timing fields are "
            "`started_at` and `completed_at`. The migration identifier "
            "column is `migration_name`, not `module_name`; migration "
            "modules are matched by this stored name. The wrong guess "
            "`migration_id` means `migration_name`; the wrong guess `failure` "
            "means `failure_reason`; and the wrong guess `source_description` "
            "means `description`. There is NO `status`, "
            "NO `model`, NO `model_id`, NO `module_name`, and NO "
            "`module` or `applied_at` column."
        ),
    },
}
