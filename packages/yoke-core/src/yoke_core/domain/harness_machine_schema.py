"""Additive schema for per-machine harness reports, keyed by project."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _add_column_if_not_exists
from yoke_core.domain.schema_init_apply import execute_schema_script


HARNESS_MACHINE_REPORTS_SQL = """
CREATE TABLE IF NOT EXISTS harness_machine_reports (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    machine_id TEXT NOT NULL DEFAULT '',
    harness_id TEXT NOT NULL,
    glue_written INTEGER NOT NULL DEFAULT 0,
    glue_present INTEGER NOT NULL DEFAULT 0,
    glue_malformed INTEGER NOT NULL DEFAULT 0,
    config_present INTEGER NOT NULL DEFAULT 0,
    project_entry_present INTEGER NOT NULL DEFAULT 0,
    approval_state TEXT NOT NULL
        CHECK(approval_state IN (
            'approved', 'unapproved', 'not_applicable', 'unknown'
        )),
    unattended_posture TEXT NOT NULL DEFAULT 'absent'
        CHECK(unattended_posture IN ('unattended', 'prompts', 'absent')),
    reported_at TEXT NOT NULL
)
"""

#: The row key, and the ``ON CONFLICT`` target the upsert names. A unique
#: index rather than a primary key so a universe born before the machine
#: column converges to the same key without a governed migration.
HARNESS_MACHINE_REPORTS_KEY_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_harness_machine_reports_key "
    "ON harness_machine_reports (project_id, machine_id, harness_id)"
)

#: The pre-machine key. It admitted one row per (project, harness), which is
#: why one machine's report answered for every machine's hook health.
LEGACY_PROJECT_HARNESS_KEY_SQL = (
    "ALTER TABLE harness_machine_reports "
    "DROP CONSTRAINT IF EXISTS harness_machine_reports_pkey"
)


def ensure_harness_machine_schema(
    conn: Any,
    *,
    commit: bool = True,
) -> None:
    """Converge machine reports, committing unless the caller owns the txn.

    The additive columns land here rather than in the shared additive pass
    because this is the only converge that knows the table exists: a universe
    that has never reported a harness has no table to alter, and the shared
    pass runs on every boot of every universe. A row that predates the
    machine column carries ``machine_id=''``, which matches no registered
    machine, so it stops answering for machines that never reported it.
    """
    execute_schema_script(conn, HARNESS_MACHINE_REPORTS_SQL)
    _add_column_if_not_exists(
        conn,
        "harness_machine_reports",
        "unattended_posture",
        "TEXT NOT NULL DEFAULT 'absent'",
    )
    _add_column_if_not_exists(
        conn, "harness_machine_reports", "machine_id", "TEXT NOT NULL DEFAULT ''",
    )
    execute_schema_script(conn, HARNESS_MACHINE_REPORTS_KEY_SQL)
    execute_schema_script(conn, LEGACY_PROJECT_HARNESS_KEY_SQL)
    if commit:
        conn.commit()


__all__ = [
    "HARNESS_MACHINE_REPORTS_KEY_SQL",
    "HARNESS_MACHINE_REPORTS_SQL",
    "LEGACY_PROJECT_HARNESS_KEY_SQL",
    "ensure_harness_machine_schema",
]
