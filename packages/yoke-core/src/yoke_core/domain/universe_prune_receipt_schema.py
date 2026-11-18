"""Additive ``universe_prune_receipts`` table: one row per scheduled prune.

Control-plane upkeep writes a row each time it runs the universe's retention
pass loop (:mod:`yoke_core.domain.universe_prune_schedule`). Boot converge
creates the table; there is no governed migration. The schedule, Doctor and
the steering report read this table, never the events journal.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


UNIVERSE_PRUNE_RECEIPTS_TABLE = "universe_prune_receipts"

#: The run deleted everything eligible under its cutoff.
OUTCOME_DRAINED = "drained"
#: The run's time budget ended with rows still eligible; upkeep continues.
OUTCOME_BUDGET = "budget"
#: The run stopped on a named refusal.
OUTCOME_FAILED = "failed"
OUTCOMES = (OUTCOME_DRAINED, OUTCOME_BUDGET, OUTCOME_FAILED)

_OUTCOME_SQL = ",".join(f"'{outcome}'" for outcome in OUTCOMES)

UNIVERSE_PRUNE_RECEIPTS_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS universe_prune_receipts (
  id INTEGER PRIMARY KEY,
  started_at TIMESTAMPTZ NOT NULL,
  completed_at TIMESTAMPTZ NOT NULL,
  elapsed_ms INTEGER NOT NULL,
  outcome TEXT NOT NULL CHECK(outcome IN ({_OUTCOME_SQL})),
  cutoff TIMESTAMPTZ,
  policy_digest TEXT NOT NULL DEFAULT '',
  deleted TEXT NOT NULL DEFAULT '{{}}',
  unfinished TEXT NOT NULL DEFAULT '[]',
  vacuumed TEXT NOT NULL DEFAULT '[]',
  failure_code TEXT NOT NULL DEFAULT '',
  failure_reason TEXT NOT NULL DEFAULT '',
  failure_recovery TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_universe_prune_receipts_started_at
  ON universe_prune_receipts (started_at DESC, id DESC);
"""


def ensure_universe_prune_receipt_schema(conn: Any) -> None:
    """Create the additive prune receipt table if it is absent."""
    execute_schema_script(conn, UNIVERSE_PRUNE_RECEIPTS_SCHEMA_SQL)


__all__ = [
    "OUTCOMES",
    "OUTCOME_BUDGET",
    "OUTCOME_DRAINED",
    "OUTCOME_FAILED",
    "UNIVERSE_PRUNE_RECEIPTS_SCHEMA_SQL",
    "UNIVERSE_PRUNE_RECEIPTS_TABLE",
    "ensure_universe_prune_receipt_schema",
]
