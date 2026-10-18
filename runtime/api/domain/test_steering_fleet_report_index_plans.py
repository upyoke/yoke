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
    JUST_NOW,
    STEERING_SESSION,
    WORKER_SESSION,
    seed_message,
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
    seed_message(
        conn,
        "current-wake",
        sender=None,
        to=WORKER_SESSION,
        at=JUST_NOW,
        idempotency_key="deployment-qa-stage-wait:run-20260927-001:item-qa:7701:digest",
    )
    # An empty analyzed table correctly favors the time index for ORDER BY.
    # Exercise the selective history lookup this index exists to accelerate.
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, body, body_sha256, selector_snapshot, "
        "created_at, expires_at, idempotency_key) "
        "SELECT 'history-' || i, sender_actor_id, body, body_sha256, "
        "selector_snapshot, created_at, expires_at, 'unrelated-history:' || i "
        "FROM session_messages CROSS JOIN generate_series(1, 2000) AS history(i) "
        "WHERE message_id = 'current-wake'"
    )
    conn.commit()
    conn.execute("ANALYZE session_messages")
    conn.execute("ANALYZE session_message_recipients")
    recorder = _Recorder(conn)
    compose_held_reports(recorder, session_id=STEERING_SESSION, now=iso8601_now())

    used: set[str] = set()
    message_plan = ""
    conn.execute("SET enable_seqscan = off")
    try:
        for sql, params in recorder.statements.items():
            plan = conn.execute(f"EXPLAIN {sql}", params).fetchall()
            text = "\n".join(str(row[0]) for row in plan)
            if "FROM session_messages m" in sql:
                message_plan = text
            used.update(name for name in INDEXES if name in text)
    finally:
        conn.execute("RESET enable_seqscan")

    assert used == INDEXES, (
        f"indexes no report statement can use: {INDEXES - used}\n{message_plan}"
    )
