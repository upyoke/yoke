"""``project`` topic table entries for the schema cheat sheet.

Sibling of :mod:`schema_api_context_tables` (which combines per-topic
dicts into the canonical ``CANONICAL_TABLES``). Holds the ``project``
topic entries: sites, environments, project_structure, path_snapshots,
project_capabilities, capability_secrets, migration_audit (delivery-lane
tables live in :mod:`schema_api_context_tables_delivery`).

Pure data only — no I/O or DB connections.
"""

from __future__ import annotations

from yoke_core.domain.schema_api_context_table_project_capabilities import (
    PROJECT_CAPABILITIES_TABLE,
)

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
            "filter. `public_item_prefix` is the work-item prefix (`YOK`, "
            "`EXT`); required on every create path, unique "
            "case-insensitively in the universe, and never derived from "
            "the slug. `id` is a JSON number on every project surface. "
            "Canonical agent read: "
            "`yoke projects list` / "
            "`yoke projects get --project <slug>`; "
            "breakage_policy reader is "
            "yoke_core.domain.projects_breakage_policy. "
            "`github_sync_mode` is the per-project GitHub sync switch "
            "(enabled | disabled; new projects default disabled; "
            "legacy NULL = enabled); reader is "
            "yoke_core.domain.projects_github_sync_mode, flip via "
            "`yoke projects update ... --github-sync-mode <mode>`. "
            "Enabling requires an active verified App binding. Find or "
            "normalize unsafe legacy rows with `yoke projects "
            "github-sync-mode repair [--apply]`. "
            "disabled turns off every backlog->GitHub issue sync "
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
            ("id", "INTEGER"),
            ("name", "TEXT"),
            ("description", "TEXT"),
            ("created_at", "TEXT"),
            ("settings", "TEXT"),
            ("project_id", "INTEGER"),
        ],
        "notes": (
            "Deployable sites use numeric internal keys and belong to projects "
            "through `sites.project_id = projects.id`; `name` is the sole "
            "human site identifier and is unique within the project. Structured "
            "site configuration lives in the JSON `settings` column. Discover "
            "site and environment names without projecting settings through "
            "`yoke projects "
            "infrastructure list --project <slug> --json` "
            "(`projects.infrastructure.list`). Legacy Pulumi operator state at "
            "`settings.pulumi.stack_state` moves transactionally through "
            "registered function `projects.pulumi_state.migrate` / `yoke "
            "projects pulumi-state migrate --project <slug> --site <name> "
            "--stack <name> [--apply]`; it dry-runs by default and emits only "
            "a redacted receipt."
        ),
    },
    "environments": {
        "columns": [
            ("id", "INTEGER"),
            ("site", "INTEGER"),
            ("project_id", "INTEGER"),
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
            "Deployment environments use numeric internal keys. `name` is the "
            "sole human environment identifier and is unique within "
            "`project_id`; the composite foreign key `(site, project_id)` keeps "
            "the numeric site and project ownership aligned. Deployment metadata such as "
            "git branch, hosts, database, and Pulumi settings lives in the "
            "JSON `settings` column. First discover metadata-only names with "
            "`yoke projects infrastructure list --project <slug> --json`; "
            "then read settings through `yoke projects "
            "environment-settings get --project <slug> --environment "
            "<name> --path <scalar.path>`; the registered function requires "
            "explicit scalar paths and returns a `values` projection. The "
            "wrong aggregate-response guess is `settings_json`: neither "
            "get nor merge returns the settings document. Merge returns "
            "only `changed_paths` plus its message. Numeric row keys never "
            "appear on these operator surfaces."
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
            "context_routing (per-topic doc paths), and deploy_defaults "
            "(default deployment_flow). Read through the family-specific "
            "domain helpers. There is no top-level context_routing table — "
            "raw queries against that name fail."
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
    "project_capabilities": PROJECT_CAPABILITIES_TABLE,
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
