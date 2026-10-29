"""Learning-log table entries for the canonical schema cheat sheet.
Pure data only — no I/O or DB connections."""

from __future__ import annotations

OUROBOROS_TABLES: dict[str, dict] = {
    "ouroboros_entries": {
        "columns": [
            ("id", "INTEGER"),
            ("timestamp", "TIMESTAMPTZ"),
            ("agent", "TEXT"),
            ("context", "TEXT"),
            ("category", "TEXT"),
            ("body", "TEXT"),
            ("reviewed_at", "TIMESTAMPTZ"),
            ("archived_at", "TIMESTAMPTZ"),
            ("created_at", "TIMESTAMPTZ"),
            ("project_id", "INTEGER"),
            ("target_project_id", "INTEGER"),
            ("correlation_id", "INTEGER"),
            ("session_id", "TEXT"),
            ("actor_id", "INTEGER"),
            ("reporter_email", "TEXT"),
            ("yoke_version", "TEXT"),
            ("universe_fingerprint", "TEXT"),
        ],
        "notes": (
            "Feedback rows store `category` and `body`; "
            "there are NO `kind` or `evidence` columns on this table. "
            "Feedback correlation_id stores the root note id; session_id "
            "stores the filing session. Minimal capture fixtures also need both "
            "columns: wrong guess that only event telemetry or feedback inserts "
            "use them; plain learning-log inserts share the same row writer. "
            "Wrong guess: attribution exists only after additive convergence; "
            "core table creation also includes actor_id and reporter metadata. "
            "Existing-universe index "
            "creation follows project_id additive convergence. "
            "Unreviewed counts exclude correlated "
            "repeats; reads attach repeat_count and bounded repeats to roots. "
            "Two project columns, both numeric; join projects for the "
            "human slug. `project_id` is where the note was OBSERVED "
            "(resolved automatically from the calling checkout). "
            "`target_project_id` is where the fix BELONGS, set only when "
            "the author declares it (`--target-project` on append) and "
            "NULL otherwise — it is never inferred. Promotion picks the "
            "caller's explicit project, else `target_project_id`, else "
            "`project_id`. "
            "`agent` holds the author label the write path resolved "
            "(subagent role, else the session's executor) — it is NOT an "
            "actor id. `actor_id` is stamped from the authenticated request, or "
            "the receiving feedback service for public notes. There is no `author` column. "
            "Nullable reporter_email, yoke_version and universe_fingerprint "
            "carry reporter metadata; a fingerprint marks untrusted public input. "
            "Category is exactly failed, new, unclear, observation or idea. "
            "Supersede links live in `ouroboros_entry_corrections`, not "
            "in a column here. "
            "Full reads order by id. Browser reads order by their selected field, "
            "defaulting to timestamp descending, with id as the tie-breaker. "
            "Browser roster reads use `ouroboros.field_note.list` with "
            "`shape=roster` (selected-field keyset cursor, matching_count, no "
            "`body`); `ouroboros.field_note.get` is the only fetch for the "
            "evidence body. Operator list/count keep offset paging and "
            "full rows — wrong guess: that the roster shape replaced "
            "that operator list or that list always carries `body`."
        ),
    },
    "ouroboros_entry_corrections": {
        "columns": [
            ("correction_entry_id", "INTEGER"),
            ("corrected_entry_id", "INTEGER"),
            ("created_at", "TIMESTAMPTZ"),
        ],
        "notes": (
            "One row per superseding feedback: `correction_entry_id` is "
            "the newer note, `corrected_entry_id` the one it replaces "
            "(both `ouroboros_entries.id`). Recording a link also stamps "
            "`reviewed_at` on the corrected note so it leaves the "
            "unreviewed queue. There is no `supersedes` column on "
            "`ouroboros_entries`; read the link through this table."
        ),
    },
}

__all__ = ["OUROBOROS_TABLES"]
