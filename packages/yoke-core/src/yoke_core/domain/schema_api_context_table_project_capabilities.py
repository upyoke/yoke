"""Project-capability packet table entry."""

from __future__ import annotations


PROJECT_CAPABILITIES_TABLE: dict[str, object] = {
    "columns": [
        ("id", "INTEGER"),
        ("project_id", "INTEGER"),
        ("type", "TEXT"),
        ("verified_at", "TIMESTAMPTZ"),
        ("created_at", "TIMESTAMPTZ"),
        ("settings", "TEXT"),
    ],
    "notes": (
        "Project capability rows keyed by `(project_id, type)`. The "
        "same commands and capability resolution apply to every project "
        "slug; every registered project is an ordinary project row, and "
        "specialized behavior comes from capabilities, environments, and "
        "workflow definitions rather than project-name checks. The "
        "capability-name column is `type` (values include "
        "`github`, `docker`, `domain`, `migration_model`, "
        "and `test_environment`); `test_environment` holds "
        "`uv_project`, `uv_extras`, and `uv_groups`, while test trees "
        "stay on Project Structure `test_roots` (wrong guess — a "
        "parallel roots capability); `settings` is a JSON blob carrying "
        "capability-specific configuration. Canonical non-sensitive settings access "
        "is `yoke projects capability-settings get --project <slug> --cap-type "
        "<type>`. Full writes use the exact returned text with "
        "`capability-settings set ... --base <as-read-json>` (or `--new` for "
        "an absent row); single-path repairs use `capability-settings merge "
        "... --set key.path=value`. These registered surfaces work over HTTPS, "
        "protect against lost updates, and run capability-specific typed "
        "canonicalization before mutation. Unknown fields on typed "
        "capabilities are refused so a mixed-version control plane cannot "
        "silently drop new authority fields. GitHub settings remain "
        "binding-owned. `pulumi-state` holds only state_bucket, "
        "kms_key_alias, deploy_namespace and "
        "component_type_aliases; it stores no stack list and no operator "
        "state. Each stack is the project's checked-in "
        "`infra/Pulumi.<stack>.yaml` (including its secretsprovider and "
        "encryptedkey lines), run with `yoke pulumi exec --project <slug> "
        "--stack <name> -- <init|preview|refresh|import|up|stack output NAME "
        "...>`; init pins `awskms://<kms_key_alias>?region=<region>` and "
        "prints the lines to commit. Single-name output reads never allow "
        "`--show-secrets`; `up` requires both `--yes` and `--non-interactive`. "
        "Retiring a stack is `destroy --yes --non-interactive` then `stack rm "
        "--yes`, each with `--confirm-destroy <name>`. "
        "Local AWS and GitHub authority comes from capability files and the "
        "selected service binding. Actions keeps AWS OIDC. "
        "The diagnostic all-capability SQL shape remains `SELECT type, settings "
        "FROM project_capabilities WHERE project_id = ?`; routine reads use the "
        "registered command instead. The Python workhorse is "
        "yoke_core.domain.projects_capabilities_settings; do not import settings "
        "helpers from projects_capabilities (wrong guess — that module owns "
        "capability listings and secrets). There are NO `project`, "
        "`capability_type`, `capability`, `key`, or `value` columns; those are "
        "stale guesses for this table. Test Machine source fixtures use "
        "yoke_core.domain.machine_qa_capability_settings.replace_test_machine_settings "
        "with explicit base_settings=None for an absent row or its as-read JSON "
        "for compare-and-swap; omitting base_settings is a wrong guess that raises "
        "TypeError before registration. Operation receipts require the matching "
        "registered project_capabilities row for their machine."
    ),
}


__all__ = ["PROJECT_CAPABILITIES_TABLE"]
