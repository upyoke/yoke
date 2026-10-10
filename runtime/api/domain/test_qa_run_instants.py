"""QA writes normalize owned clocks without changing captures or FIFO authority."""

from datetime import datetime, timedelta
import json
import sqlite3

import pytest

from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain.qa_constants import _pipe_row
from yoke_core.domain.qa_plan_execution_authority import (
    PLAN_EXECUTION_STALE_SECONDS,
    plan_execution_is_stale,
)
from yoke_core.domain.qa_plan_execution_store import canonical
from yoke_core.domain.qa_run_verdict_record import insert_qa_run, update_qa_run


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_run_writes_bind_native_clocks_and_preserve_capture_bytes(test_db, zone):
    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    instant = parse_instant("1969-12-31T23:59:59.999999Z")
    requirement = insert_qa_requirement(test_db, created_at=instant)
    evidence = '{"immutable":"1969-12-31T19:00:00-05:00"}'
    written = insert_qa_run(
        test_db,
        qa_requirement_id=requirement["id"],
        performed_by="agent",
        qa_kind="smoke",
        verdict=None,
        started_at="1970-01-01T05:29:59.999999+05:30",
        completed_at=None,
        created_at=instant,
        raw_result=evidence,
    )
    before = test_db.execute(
        "SELECT started_at,completed_at,created_at,raw_result FROM qa_runs WHERE id=%s",
        (written.run_id,),
    ).fetchone()
    assert tuple(before) == (instant, None, instant, evidence)
    endpoint = instant + timedelta(microseconds=1)
    update_qa_run(
        test_db, written.run_id, {"verdict": "fail"}, default_completed_at=endpoint
    )
    update_qa_run(
        test_db,
        written.run_id,
        {"verdict_reason": "captured"},
        default_completed_at=endpoint + timedelta(days=1),
    )
    after = test_db.execute(
        "SELECT started_at,completed_at,created_at,raw_result FROM qa_runs WHERE id=%s",
        (written.run_id,),
    ).fetchone()
    assert tuple(after) == (instant, endpoint, instant, evidence)
    assert _pipe_row(tuple(after)[:3]) == "|".join(
        [format_instant(instant), format_instant(endpoint), format_instant(instant)]
    )


def test_sqlite_owned_clock_storage_and_new_result_encoding_are_canonical():
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            "CREATE TABLE qa_runs(id INTEGER PRIMARY KEY, qa_requirement_id INTEGER,"
            "verdict TEXT, started_at TEXT, completed_at TEXT, created_at TEXT, raw_result TEXT)"
        )
        instant = parse_instant("1969-12-31T23:59:59.999999Z")
        original = '{"immutable":"1969-12-31T19:00:00-05:00"}'
        written = insert_qa_run(
            conn,
            qa_requirement_id=1,
            verdict=None,
            started_at=instant,
            completed_at=None,
            created_at=instant,
            raw_result=original,
        )
        endpoint = instant + timedelta(microseconds=1)
        update_qa_run(
            conn, written.run_id, {"verdict": "fail"}, default_completed_at=endpoint
        )
        assert conn.execute(
            "SELECT started_at,completed_at,created_at,raw_result FROM qa_runs"
        ).fetchone() == (
            format_instant(instant),
            format_instant(endpoint),
            format_instant(instant),
            original,
        )
        encoded = canonical({"completed_at": endpoint, "opaque": original})
        assert json.loads(encoded) == {
            "completed_at": format_instant(endpoint),
            "opaque": original,
        }
        assert canonical(json.loads(original)) == original
    finally:
        conn.close()


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "1970-01-01",
        "1970-01-01T00:00:00",
        "1970-01-01T00:00:00.1234567Z",
        datetime(1970, 1, 1),
    ],
)
def test_invalid_clock_refuses_before_any_lock_or_database_call(bad):
    class Untouched:
        def execute(self, *args):
            pytest.fail("invalid clock reached a database operation")

    conn = Untouched()
    with pytest.raises(InvalidInstant):
        insert_qa_run(conn, qa_requirement_id=1, started_at=bad)
    with pytest.raises(InvalidInstant):
        update_qa_run(conn, 1, {"completed_at": bad})
    with pytest.raises(InvalidInstant):
        update_qa_run(conn, 1, {"verdict": "pass"}, default_completed_at=bad)
    with pytest.raises(InvalidInstant):
        plan_execution_is_stale({"heartbeat_at": bad})


def test_missing_heartbeat_is_stale_but_exact_boundary_retains_authority():
    now = parse_instant("1969-12-31T23:59:59.999999Z")
    endpoint = now - timedelta(seconds=PLAN_EXECUTION_STALE_SECONDS)
    assert plan_execution_is_stale({"heartbeat_at": None}, now=now)
    assert not plan_execution_is_stale({"heartbeat_at": endpoint}, now=now)
    assert plan_execution_is_stale(
        {"heartbeat_at": endpoint - timedelta(microseconds=1)}, now=now
    )
    with pytest.raises(InvalidInstant):
        plan_execution_is_stale({"heartbeat_at": endpoint}, now=datetime(1970, 1, 1))


def test_host_fifo_orders_equivalent_offsets_by_instant_and_keeps_id_ties(test_db):
    from runtime.api.domain.machine_qa_session_seed import seed_qa_session
    from runtime.api.domain.test_qa_host_turns import _queue
    from yoke_core.domain.qa_host_turns import queued_host_turns

    seed_qa_session(test_db, "first", "later", "equal")
    later = _queue(test_db, "later", when="1970-01-01T00:00:00.000001Z")
    first = _queue(test_db, "first", when="1970-01-01T05:30:00.000000+05:30")
    equal = _queue(test_db, "equal", when="1969-12-31T19:00:00.000000-05:00")
    assert [row["id"] for row in queued_host_turns(test_db, "linux-lab")] == [
        first,
        equal,
        later,
    ]
