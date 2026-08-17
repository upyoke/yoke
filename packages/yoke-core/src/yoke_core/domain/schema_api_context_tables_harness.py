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
            "Primary key is (project_id, harness_id). There is no machines "
            "table, no project_installs table, and no ProjectInstalled "
            "event — a hookless harness produces no server-visible fact "
            "until this row is upserted. approval_state is "
            "approved|unapproved|not_applicable|unknown. Orange health "
            "is approval_state=unapproved (presence of any hooks.state "
            "entry keyed to the literal .codex/hooks.json path; no "
            "hashing). Write through harness.machine_report.upsert."
        ),
    },
}


__all__ = ["HARNESS_TABLES"]
