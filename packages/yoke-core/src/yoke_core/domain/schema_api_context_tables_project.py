"""``project`` topic table entries for the schema cheat sheet.

Sibling of :mod:`schema_api_context_tables` (which combines per-topic
dicts into the canonical ``CANONICAL_TABLES``). Holds the ``project``
topic entries: project_structure, deployment_flows, deployment_runs,
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
            "(enabled | backlog_only; NULL = enabled); reader is "
            "yoke_core.domain.projects_github_sync_mode, flip via "
            "`yoke projects update ... --github-sync-mode <mode>`. "
            "backlog_only turns off every backlog->GitHub issue sync "
            "surface for the project — the logged skip line is policy, "
            "not an auth failure. "
            "Project-scoped settings do NOT live on a `projects.settings` "
            "column; use `project_structure`, `project_capabilities.settings`, "
            "or environment settings surfaces for those aggregates."
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
        ],
        "notes": (
            "Deployment-flow definitions keyed by TEXT `id`. Project "
            "lookup uses numeric `project_id`; join projects for the slug. "
            "The human flow name is `name`. "
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
            "through `deployment_run_items`; environment-level deploys "
            "(for example a Yoke prod/stage redeploy) intentionally "
            "have zero member rows and still advance this run row. To "
            "find the active deploy run for an item, JOIN through "
            "`deployment_run_items`: `SELECT dr.id, dr.status, "
            "dr.current_stage, dr.target_env FROM deployment_runs dr "
            "JOIN deployment_run_items dri ON dri.run_id = dr.id WHERE "
            "dri.item_id = ? ORDER BY dr.created_at DESC LIMIT 1;`. "
            "Use `deployment_runs.id` in raw run queries; do not look "
            "for a `run_id` column on the run table (that column lives "
            "on `deployment_run_items`). "
            "Stale-run HCs scan rows where `status` is non-terminal "
            "but `started_at` is older than the configured cutoff; "
            "item-less is suspicious only when a run never starts."
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
            "configuration. Resolve the project slug to `projects.id`, then "
            "query by `project_id`. Canonical lookups: `SELECT type, "
            "settings FROM project_capabilities WHERE project_id = ?;` for "
            "every capability on a project; `SELECT NULLIF(settings, '')::jsonb "
            "#>> '{repo_owner}' FROM project_capabilities WHERE project_id "
            "= ? AND type = 'github';` to pull a single JSON field. "
            "Python helper for non-secret settings reads: "
            "yoke_core.domain.projects_capabilities_settings."
            "cmd_capability_get_settings; do not import "
            "cmd_capability_get_settings from projects_capabilities "
            "(wrong guess — that module owns capability listings and "
            "secrets). "
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
            "modules are matched by this stored name. There is NO `status`, "
            "NO `model`, NO `model_id`, NO `module_name`, and NO "
            "`module` or `applied_at` column."
        ),
    },
}
