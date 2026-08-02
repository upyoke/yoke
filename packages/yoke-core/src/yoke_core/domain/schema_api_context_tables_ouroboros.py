"""Learning-log table entries for the canonical schema cheat sheet.
Pure data only — no I/O or DB connections."""

from __future__ import annotations

OUROBOROS_TABLES: dict[str, dict] = {
    "ouroboros_entries": {
        "columns": [
            ("id", "INTEGER"),
            ("timestamp", "TEXT"),
            ("agent", "TEXT"),
            ("context", "TEXT"),
            ("category", "TEXT"),
            ("body", "TEXT"),
            ("reviewed_at", "TEXT"),
            ("archived_at", "TEXT"),
            ("created_at", "TEXT"),
            ("project_id", "INTEGER"),
        ],
        "notes": (
            "Learning-log / field-note rows. The kind-like discriminator "
            "is `category` and the evidence/content text is `body`; "
            "there are NO `kind` or `evidence` columns on this table. "
            "Project authority is numeric `project_id`; join projects for "
            "the human slug. "
            "`agent` holds the author label the write path resolved "
            "(subagent role, else the session's executor) — it is NOT an "
            "actor id, and there is no `author` or `actor_id` column. "
            "Supersede links live in `ouroboros_entry_corrections`, not "
            "in a column here. "
            "Use `created_at` for canonical ordering; `timestamp` is "
            "legacy compatibility."
        ),
    },
    "ouroboros_entry_corrections": {
        "columns": [
            ("correction_entry_id", "INTEGER"),
            ("corrected_entry_id", "INTEGER"),
            ("created_at", "TEXT"),
        ],
        "notes": (
            "One row per superseding field note: `correction_entry_id` is "
            "the newer note, `corrected_entry_id` the one it replaces "
            "(both `ouroboros_entries.id`). Recording a link also stamps "
            "`reviewed_at` on the corrected note so it leaves the "
            "unreviewed queue. There is no `supersedes` column on "
            "`ouroboros_entries`; read the link through this table."
        ),
    },
}

__all__ = ["OUROBOROS_TABLES"]
