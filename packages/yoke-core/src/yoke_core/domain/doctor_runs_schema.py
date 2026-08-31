"""Additive ``doctor_runs`` receipt table.

One row per completed Doctor run. Boot converge creates the table; there
is no governed migration. Application code reads this table — never the
events journal — for the latest health receipt.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


DOCTOR_RUNS_TABLE = "doctor_runs"

DOCTOR_RUNS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS doctor_runs (
  id INTEGER PRIMARY KEY,
  ran_at TEXT NOT NULL,
  project TEXT NOT NULL,
  scope TEXT,
  runtime TEXT,
  fail_count INTEGER NOT NULL DEFAULT 0,
  pass_count INTEGER NOT NULL DEFAULT 0,
  warn_count INTEGER NOT NULL DEFAULT 0,
  na_count INTEGER NOT NULL DEFAULT 0,
  results TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_doctor_runs_project_ran_at
  ON doctor_runs (project, ran_at DESC, id DESC);
"""


def ensure_doctor_runs_schema(conn: Any) -> None:
    """Create the additive doctor-run receipt table if it is absent."""
    execute_schema_script(conn, DOCTOR_RUNS_SCHEMA_SQL)
    conn.commit()


__all__ = [
    "DOCTOR_RUNS_SCHEMA_SQL",
    "DOCTOR_RUNS_TABLE",
    "ensure_doctor_runs_schema",
]
