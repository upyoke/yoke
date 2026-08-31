"""``doctor_runs`` table entry for the schema cheat sheet.

Sibling of :mod:`schema_api_context_tables`. Doctor receipts are a
dedicated table; they are not reconstructed from the events journal.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


DOCTOR_TABLES: dict[str, dict] = {
    "doctor_runs": {
        "columns": [
            ("id", "INTEGER"),
            ("ran_at", "TEXT"),
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
            "`yoke status` read it; never scan events."
        ),
    },
}


__all__ = ["DOCTOR_TABLES"]
