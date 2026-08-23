"""``harness_machine_reports`` packet teaching.

Wrong guesses this table exists to catch: ``project_installs``,
``machines``, ``harness_installs``. Those tables do not exist. Install
already computed which glue it wrote and used to discard it; this row is
that durable record plus later client-collected presence.
"""

from __future__ import annotations


HARNESS_TABLES: dict[str, dict] = {
    "harness_machine_reports": {
        "columns": [
            ("project_id", "INTEGER"),
            ("harness_id", "TEXT"),
            ("glue_written", "INTEGER"),
            ("glue_present", "INTEGER"),
            ("glue_malformed", "INTEGER"),
            ("config_present", "INTEGER"),
            ("project_entry_present", "INTEGER"),
            ("approval_state", "TEXT"),
            ("reported_at", "TEXT"),
        ],
        "notes": (
            "PK (project_id, harness_id). No machines, project_installs, "
            "or harness_installs table. approval_state is "
            "approved|unapproved|not_applicable|unknown; orange is "
            "unapproved (every normalized .codex/hooks.json handler must "
            "match trusted_hash under the literal hooks-file path). Write "
            "via harness.machine_report.upsert."
        ),
    },
}


__all__ = ["HARNESS_TABLES"]
