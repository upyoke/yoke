"""``doctor_runs`` and ``universe_prune_receipts`` cheat-sheet entries.

Sibling of :mod:`schema_api_context_tables`. Doctor and scheduled prune
receipts are dedicated tables; they are not reconstructed from events.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


DOCTOR_TABLES: dict[str, dict] = {
    "doctor_runs": {
        "columns": [
            ("id", "INTEGER"),
            ("ran_at", "TIMESTAMPTZ"),
            ("project", "TEXT"),
            ("scope", "TEXT"),
            ("runtime", "TEXT"),
            ("fail_count", "INTEGER"),
            ("pass_count", "INTEGER"),
            ("warn_count", "INTEGER"),
            ("na_count", "INTEGER"),
            ("results", "TEXT"),
        ],
        "notes": (
            "Newest `doctor.run.run` receipt. `doctor.last_run.get` and "
            "`yoke status` read it; never scan events. "
            "The session-cwd doctor check calls "
            "yoke_core.domain.lint_session_cwd_validate.validate_targets. "
            "Wrong guess: its retired yoke_root keyword still exists; "
            "repository scope now comes only from recorded lane roots."
        ),
    },
    "universe_prune_receipts": {
        "columns": [
            ("id", "INTEGER"),
            ("started_at", "TIMESTAMPTZ"),
            ("completed_at", "TIMESTAMPTZ"),
            ("elapsed_ms", "INTEGER"),
            ("outcome", "TEXT"),
            ("cutoff", "TIMESTAMPTZ"),
            ("policy_digest", "TEXT"),
            ("deleted", "TEXT"),
            ("unfinished", "TEXT"),
            ("vacuumed", "TEXT"),
            ("failure_code", "TEXT"),
            ("failure_reason", "TEXT"),
            ("failure_recovery", "TEXT"),
        ],
        "notes": (
            "One row per scheduled prune run by control-plane upkeep. "
            "outcome is drained, budget (more remains; the next upkeep "
            "cycle continues) or failed (failure_* names the refusal). "
            "deleted is a JSON object of rows deleted per table. A foreground "
            "`yoke universe prune` writes no receipt."
        ),
    },
}


__all__ = ["DOCTOR_TABLES"]
