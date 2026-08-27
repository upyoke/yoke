"""Generated-board visibility for live steering scopes."""

from __future__ import annotations

import contextlib
from pathlib import Path

from yoke_contracts.board.sections_steering import render_steering_section
from yoke_contracts.session_control.launch_origin import (
    LAUNCH_ORIGIN_STEERING_BACKSTOP,
)
from yoke_contracts.turn_end_evidence import steering_report_idempotency_key
from yoke_core.board.db import BoardDB
from yoke_core.domain.work_claim_targets import make_steering_target
from runtime.api.fixtures.file_test_db import (
    apply_inline_ddl,
    connect_test_db,
    init_test_db,
)


_SCHEMA = """
CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT UNIQUE);
CREATE TABLE harness_sessions (
    session_id TEXT PRIMARY KEY,
    project_id INTEGER,
    last_heartbeat TEXT,
    last_tool_call_at TEXT,
    ended_at TEXT,
    terminated_at TEXT
);
CREATE TABLE work_claims (
    id INTEGER PRIMARY KEY,
    session_id TEXT,
    target_kind TEXT,
    scope TEXT,
    claimed_at TEXT,
    released_at TEXT
);
CREATE TABLE strategy_doc_claims (
    project_id INTEGER,
    strategy_doc_slug TEXT,
    owner_kind TEXT,
    owner_session_id TEXT,
    released_at TEXT
);
CREATE TABLE session_launches (
    launch_id TEXT PRIMARY KEY,
    requester_session_id TEXT,
    project_id INTEGER,
    origin TEXT
);
CREATE TABLE session_launch_attempts (
    launch_id TEXT,
    native_session_id TEXT,
    started_at TEXT,
    attempt_number INTEGER
);
CREATE TABLE session_messages (
    message_id TEXT PRIMARY KEY,
    sender_session_id TEXT,
    idempotency_key TEXT,
    created_at TEXT
);
CREATE TABLE session_message_recipients (
    message_id TEXT,
    session_id TEXT,
    project_id INTEGER,
    state TEXT
);
"""


@contextlib.contextmanager
def _board_db(tmp_path: Path):
    with init_test_db(
        tmp_path,
        apply_schema=lambda: apply_inline_ddl(_SCHEMA),
    ) as db_path:
        db = BoardDB(db_path)
        try:
            yield db, db_path
        finally:
            db.close()


def _seed(db_path: str) -> None:
    conn = connect_test_db(db_path)
    try:
        for row in ((1, "yoke"), (2, "external")):
            conn.execute("INSERT INTO projects VALUES (%s,%s)", row)
        for row in (
            ("holder-1", 1, "2026-08-26T12:00:00Z"),
            ("worker-1", 1, "2026-08-26T12:01:00Z"),
            ("holder-2", 2, "2026-08-26T12:00:00Z"),
        ):
            conn.execute(
                "INSERT INTO harness_sessions VALUES (%s,%s,%s,NULL,NULL,NULL)",
                row,
            )
        for row in (
            (
                1,
                "holder-1",
                make_steering_target(1).scope_json(),
                "2026-08-26T11:00:00Z",
            ),
            (
                2,
                "holder-2",
                make_steering_target(2).scope_json(),
                "2026-08-26T11:00:00Z",
            ),
        ):
            conn.execute(
                "INSERT INTO work_claims VALUES (%s,%s,'steering',%s,%s,NULL)",
                row,
            )
        conn.execute(
            "INSERT INTO strategy_doc_claims VALUES "
            "(1,'MISSION','session','holder-1',NULL)"
        )
        conn.execute(
            "INSERT INTO session_launches VALUES (%s,%s,%s,%s)",
            ("launch-1", "holder-1", 1, LAUNCH_ORIGIN_STEERING_BACKSTOP),
        )
        conn.execute(
            "INSERT INTO session_launch_attempts VALUES "
            "('launch-1','worker-1','2026-08-26T11:30:00Z',1)"
        )
        conn.execute(
            "INSERT INTO session_messages VALUES (%s,%s,%s,%s)",
            (
                "message-1",
                "operator-1",
                steering_report_idempotency_key("operator-1", "fingerprint"),
                "2026-08-26T12:02:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO session_message_recipients VALUES "
            "('message-1','holder-1',1,'pending')"
        )
        conn.commit()
    finally:
        conn.close()


def test_renders_scoped_holder_docs_liveness_workers_and_reports(
    tmp_path: Path,
) -> None:
    with _board_db(tmp_path) as (db, db_path):
        _seed(db_path)
        text = render_steering_section(db, "yoke")

    assert "Steering (1)" in text
    assert "yoke · MISSION" in text
    assert "`holder-1`" in text
    assert "alive ·" in text
    assert "| 1       | 1       |" in text
    assert "external" not in text


def test_a_killed_holder_reads_ended_with_its_cause(tmp_path: Path) -> None:
    # Liveness has no `terminated` value; a kill is a cause of death.
    with _board_db(tmp_path) as (db, db_path):
        _seed(db_path)
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE harness_sessions SET ended_at=%s,terminated_at=%s "
            "WHERE session_id='holder-1'",
            ("2026-08-26T12:05:00Z", "2026-08-26T12:05:00Z"),
        )
        conn.commit()
        conn.close()
        text = render_steering_section(db, "yoke")

    assert "ended · killed" in text
    assert "terminated" not in text


def test_renders_an_explicit_empty_state(tmp_path: Path) -> None:
    with _board_db(tmp_path) as (db, db_path):
        conn = connect_test_db(db_path)
        conn.execute("INSERT INTO projects VALUES (1,'yoke')")
        conn.commit()
        conn.close()
        text = render_steering_section(db, "all")

    assert text == (
        "### 🧭 Steering\n\n_No active steering scopes in this board view._"
    )
