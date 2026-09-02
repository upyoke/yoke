"""Additive schema for per-project harness machine reports."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_common import _add_column_if_not_exists
from yoke_core.domain.schema_init_apply import execute_schema_script


HARNESS_MACHINE_REPORTS_SQL = """
CREATE TABLE IF NOT EXISTS harness_machine_reports (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
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
    reported_at TEXT NOT NULL,
    PRIMARY KEY (project_id, harness_id)
)
"""


def ensure_harness_machine_schema(
    conn: Any,
    *,
    commit: bool = True,
) -> None:
    """Converge machine reports, committing unless the caller owns the txn.

    The additive column lands here rather than in the shared additive pass
    because this is the only converge that knows the table exists: a universe
    that has never reported a harness has no table to alter, and the shared
    pass runs on every boot of every universe.
    """
    execute_schema_script(conn, HARNESS_MACHINE_REPORTS_SQL)
    _add_column_if_not_exists(
        conn,
        "harness_machine_reports",
        "unattended_posture",
        "TEXT NOT NULL DEFAULT 'absent'",
    )
    if commit:
        conn.commit()


__all__ = ["HARNESS_MACHINE_REPORTS_SQL", "ensure_harness_machine_schema"]
