"""Read-only migration composition recipes for integration evidence."""

from __future__ import annotations


MIGRATION_COMMANDS: list[dict] = [
    {
        "topic": "core",
        "roles": ("main_agent", "simulator_agent"),
        "startup_roles": ("simulator_agent",),
        "purpose": "Read migration composition ledger and rehearsal evidence",
        "recipe": (
            'yoke db read "SELECT migration_name, applied_at, applied_by, '
            "minimum_serving_version, content_sha256 FROM applied_migrations "
            "WHERE migration_name IN ('OLD_NAME', 'FINAL_NAME') "
            'ORDER BY migration_name"\n'
            'yoke db read "SELECT id, migration_name, project_id, model_name, '
            "state, source_commit, source_fingerprint, rehearsed_at, "
            "failure_reason FROM migration_audit WHERE project_id = PROJECT_ID "
            "AND model_name = 'MODEL' AND migration_name IN "
            "('OLD_NAME', 'FINAL_NAME') ORDER BY id\"\n"
            'yoke db read "SELECT migration_name, content_sha256, '
            "artifact_engine_version, source_artifact, source_sha256, "
            "source_commit, manifest_sha256, adopted_by, adopted_at "
            "FROM migration_content_adoptions WHERE migration_name IN "
            "('OLD_NAME', 'FINAL_NAME') ORDER BY migration_name\""
        ),
        "notes": (
            "Substitute all old and final module names, the resolved integer "
            "project id and declared model name. Ledger/adoption reads target "
            "each model's declared authoritative database via its configured "
            "connection; migration_audit is read on the control plane holding "
            "the item. Label each source and read time, including explicit "
            "empty results. These Yoke table names are not generic defaults: "
            "other projects use their migration_model ledger/evidence contract. "
            "Conduct supplies the rows, final ordinal mapping and accepted "
            "final rehearsal audit ids before every standard/compressed/retry "
            "integration dispatch. An applied old name blocks renumbering; "
            "unreadable evidence or missing final rehearsal receipts needs "
            "access/rehearsal recovery, never a guessed table or ledger rewrite."
        ),
    },
]
