"""Durable merge-queue landing observations and project refresh cadence."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.merge_queue_landing_record_state import LANDING_RECORD_STATES
from yoke_core.domain.schema_init_apply import execute_schema_script


_STATE_SQL = ",".join(f"'{state}'" for state in LANDING_RECORD_STATES)

MERGE_QUEUE_LANDING_RECORDS_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS merge_queue_landing_records (
  item_id INTEGER PRIMARY KEY REFERENCES items(id),
  project_id INTEGER NOT NULL REFERENCES projects(id),
  pr_number TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ({_STATE_SQL})),
  head_sha TEXT NOT NULL DEFAULT '',
  failed_checks TEXT NOT NULL DEFAULT '[]',
  narrative TEXT NOT NULL DEFAULT '',
  disarm_note TEXT NOT NULL DEFAULT '',
  observed_at TEXT NOT NULL,
  changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_merge_queue_landing_records_project
  ON merge_queue_landing_records(project_id, observed_at);
CREATE TABLE IF NOT EXISTS merge_queue_landing_refreshes (
  project_id INTEGER PRIMARY KEY REFERENCES projects(id),
  started_at TEXT NOT NULL,
  completed_at TEXT,
  last_error TEXT NOT NULL DEFAULT ''
);
"""


def ensure_merge_queue_landing_record_schema(conn: Any) -> None:
    """Converge the additive landing-record tables on ``conn``."""
    execute_schema_script(conn, MERGE_QUEUE_LANDING_RECORDS_CREATE_SQL)


__all__ = [
    "LANDING_RECORD_STATES",
    "MERGE_QUEUE_LANDING_RECORDS_CREATE_SQL",
    "ensure_merge_queue_landing_record_schema",
]
