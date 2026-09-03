"""A launched native that dies before its worker starts corrects its launch."""

from __future__ import annotations

import json

from yoke_core.domain import session_launch_abandonment as launch_abandonment
from yoke_core.domain.session_launch_abandonment import (
    ABANDONED_RESULT_CODE,
    abandonment_notice,
)
from runtime.api.domain.session_launch_test_support import NOW, add_relay
from runtime.api.domain.test_session_launch_abandonment import (
    WORKER,
    _delivered_launch,
    _worker_tables,
    launch_connection,
)


def _events_table(conn) -> None:
    """Add the tool-call evidence the native-death check reads."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            event_name TEXT
        )"""
    )
    conn.commit()


def _death_evidence() -> dict[str, object]:
    return {
        "launch_id": "launch-1",
        "exit_code": 1,
        "native_diagnostic_ref": "nd-11111111-1111-4111-8111-111111111111",
        "native_exit_at": "2026-08-22T12:03:00Z",
        "native_stderr_tail": "credit balance is too low",
    }


def test_a_native_that_dies_before_working_flips_its_launch_immediately() -> None:
    conn = launch_connection()
    _worker_tables(conn)
    _events_table(conn)
    add_relay(conn)
    assert _delivered_launch(conn).state == "succeeded"

    flipped = launch_abandonment.settle_launch_native_death(
        conn,
        WORKER,
        _death_evidence(),
        now="2026-08-22T12:03:05Z",
    )

    assert flipped is not None
    assert flipped.state == "failed"
    assert flipped.result_code == ABANDONED_RESULT_CODE
    evidence = json.loads(flipped.result_evidence)
    # The reason travels with the correction, so the launch row explains
    # itself without anyone opening the machine-local capture.
    assert evidence["closure_reason"] == (
        "native_process_gone: credit balance is too low"
    )
    assert evidence["native_stderr_tail"] == "credit balance is too low"
    assert evidence["exit_code"] == 1
    assert evidence["native_exit_at"] == "2026-08-22T12:03:00Z"
    assert (
        evidence["native_diagnostic_ref"] == "nd-11111111-1111-4111-8111-111111111111"
    )


def test_a_native_that_completed_a_tool_call_keeps_its_launch() -> None:
    conn = launch_connection()
    _worker_tables(conn)
    _events_table(conn)
    add_relay(conn)
    _delivered_launch(conn)
    # A worker killed mid-work was working; only one that never began is a
    # launch that reported success for nothing.
    conn.execute(
        "INSERT INTO events (session_id, event_name) VALUES (?, ?)",
        (WORKER, "HarnessToolCallCompleted"),
    )
    conn.commit()

    assert (
        launch_abandonment.settle_launch_native_death(
            conn, WORKER, _death_evidence(), now=NOW
        )
        is None
    )


def test_a_native_death_without_a_tail_still_names_why_it_flipped() -> None:
    conn = launch_connection()
    _worker_tables(conn)
    _events_table(conn)
    add_relay(conn)
    _delivered_launch(conn)

    flipped = launch_abandonment.settle_launch_native_death(
        conn, WORKER, {"launch_id": "launch-1"}, now=NOW
    )

    assert flipped is not None
    assert json.loads(flipped.result_evidence)["closure_reason"] == (
        launch_abandonment.NATIVE_PROCESS_GONE_REASON
    )


def test_the_native_death_notice_quotes_what_the_native_said() -> None:
    conn = launch_connection()
    _worker_tables(conn)
    _events_table(conn)
    add_relay(conn)
    _delivered_launch(conn)

    flipped = launch_abandonment.settle_launch_native_death(
        conn, WORKER, _death_evidence(), now=NOW
    )

    assert flipped is not None
    notice = abandonment_notice(flipped, WORKER)
    assert "the native running session" in notice
    assert "credit balance is too low" in notice
    assert ABANDONED_RESULT_CODE in notice
