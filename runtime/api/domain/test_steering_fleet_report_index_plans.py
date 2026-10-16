"""The report's history-scanning reads have an index each can use.

Measured on production data, four reads scanned whole tables that only
grow: live sessions among every session ever registered, an item's claims
among every claim, a session's launch among every launch, and a run's wake
notices among every message. Each now has an index. The plans here are
taken from the statements the report itself issues, so an index that no
longer matches its query's expression fails here rather than silently
falling back to a scan.
"""

from __future__ import annotations

from typing import Any

from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from runtime.api.steering_fleet_test_helpers import (
    STEERING_SESSION,
    seed_steering_scope,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.steering_fleet_report_compose import compose_held_reports


INDEXES = {
    "idx_harness_sessions_live",
    "idx_session_launches_registered_session",
    "idx_session_messages_idempotency_prefix",
    "idx_work_claims_item_history",
}


class _Recorder:
    def __init__(self, inner: Any) -> None:
        self._conn = inner
        self.statements: dict[str, tuple[Any, ...]] = {}

    def execute(self, sql: str, params: Any = ()) -> Any:
        if str(sql).lstrip().upper().startswith("SELECT"):
            self.statements.setdefault(str(sql), tuple(params or ()))
        return self._conn.execute(sql, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def test_each_history_scan_has_an_index_its_statement_uses(test_db) -> None:
    conn = seed_steering_scope(test_db)
    seed_run_standing_on_qa_stage(
        conn,
        run_id="run-20260927-001",
        project="yoke",
        stages=item_qa_stage_definitions(None),
        members=(7701, 7702),
        lineage="f" * 40,
    )
    release_seeded_driver(conn, "run-20260927-001")
    conn.commit()
    recorder = _Recorder(conn)
    compose_held_reports(recorder, session_id=STEERING_SESSION, now=iso8601_now())

    used: set[str] = set()
    conn.execute("SET enable_seqscan = off")
    try:
        for sql, params in recorder.statements.items():
            plan = conn.execute(f"EXPLAIN {sql}", params).fetchall()
            text = "\n".join(str(row[0]) for row in plan)
            used.update(name for name in INDEXES if name in text)
    finally:
        conn.execute("RESET enable_seqscan")

    assert used == INDEXES, f"indexes no report statement can use: {INDEXES - used}"
