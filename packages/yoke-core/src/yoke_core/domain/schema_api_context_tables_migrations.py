"""Migration ledger and content-provenance facts for diagnostic packets."""

from __future__ import annotations


MIGRATION_TABLES: dict[str, dict] = {
    "applied_migrations": {
        "columns": [
            ("migration_name", "TEXT"),
            ("applied_at", "TIMESTAMPTZ"),
            ("applied_by", "TEXT"),
            ("minimum_serving_version", "TEXT"),
            ("content_sha256", "TEXT"),
        ],
        "notes": (
            "Permanent applied-name ledger, on each database the model owns; "
            "pending means history minus this ledger. There is no guessed "
            "`schema_migrations` table or numeric `version` cursor. "
            "An applied migration cannot be renumbered. Read both old and final "
            "names and preserve empty results with source identity/read time. "
            "These are Yoke's names; other projects declare their ledger in "
            "migration_model. Rehearsal evidence lives separately in the "
            "item control plane's migration_audit."
        ),
    },
    "migration_content_adoptions": {
        "columns": [
            ("migration_name", "TEXT"),
            ("content_sha256", "TEXT"),
            ("artifact_engine_version", "TEXT"),
            ("source_artifact", "TEXT"),
            ("source_sha256", "TEXT"),
            ("source_commit", "TEXT"),
            ("manifest_sha256", "TEXT"),
            ("adopted_by", "TEXT"),
            ("adopted_at", "TIMESTAMPTZ"),
        ],
        "notes": (
            "Append-only content identity adoption evidence, keyed by "
            "migration_name; not a migration apply or rehearsal receipt. "
            "Read alongside applied_migrations for old and final names; "
            "an empty adoption result does not prove an entry is unapplied. "
            "Never mutate adoption evidence or ledger names during composition."
        ),
    },
}
