"""One row per session waiting in a physical Test Machine's line.

A ``QA_HOST:<machine>`` claim admits one session at a time. A session
refused because another holds the host joins this line instead of retrying
blind: a scoped QA plan execution joins when its case cannot lease the
host, and a manual ``yoke claims coordination-claim acquire`` joins when it
is refused ``claim_held``. Every release of the host reserves it for the
oldest live waiter and wakes that session; the waiter's next acquire
consumes the reservation.

States: ``waiting`` (in line), ``reserved`` (the host is held for this
waiter as ``claim_id``), ``granted`` (the waiter's acquire consumed the
reservation) and ``cancelled`` (the waiter's session ended, its execution
settled or moved hosts, or the reservation was released unused).
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script

QA_TEST_MACHINE_WAIT_TABLE = "qa_test_machine_waits"
LIVE_TEST_MACHINE_WAIT_STATES = ("waiting", "reserved")

QA_TEST_MACHINE_WAIT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS qa_test_machine_waits (
    id TEXT PRIMARY KEY,
    test_machine TEXT NOT NULL,
    session_id TEXT NOT NULL,
    actor_id INTEGER NOT NULL,
    queued_at TIMESTAMPTZ NOT NULL,
    qa_plan_execution_id TEXT REFERENCES qa_plan_executions(id),
    state TEXT NOT NULL CHECK(state IN ('waiting','reserved','granted','cancelled')),
    claim_id INTEGER REFERENCES work_claims(id),
    resume_command TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    settled_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_test_machine_waits_live_session
    ON qa_test_machine_waits(test_machine, session_id)
    WHERE state IN ('waiting','reserved');
CREATE INDEX IF NOT EXISTS idx_qa_test_machine_waits_line
    ON qa_test_machine_waits(test_machine, state, queued_at);
"""


def ensure_qa_test_machine_wait_schema(conn: Any) -> None:
    """Converge the additive Test Machine waiting-line table on ``conn``."""
    execute_schema_script(conn, QA_TEST_MACHINE_WAIT_SCHEMA_SQL)


__all__ = [
    "LIVE_TEST_MACHINE_WAIT_STATES",
    "QA_TEST_MACHINE_WAIT_SCHEMA_SQL",
    "QA_TEST_MACHINE_WAIT_TABLE",
    "ensure_qa_test_machine_wait_schema",
]
