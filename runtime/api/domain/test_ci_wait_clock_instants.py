"""CI wait SQL facts and inclusive poll cutoffs retain native precision."""

from datetime import datetime, timedelta
import sqlite3

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain.handlers import session_ci_wait_writes as writes
from yoke_core.domain import session_ci_wait_observer as observer
from yoke_core.domain.session_ci_wait_schema import ensure_session_ci_wait_schema
from runtime.api.domain.coordination_claim_test_support import seed_session

MOMENT = parse_instant("2026-10-09T16:11:12.345678+05:45")
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]
OPAQUE = "captured output 2026-10-09 10:26:12+00:00"


def _seed(conn):
    seed_session(conn, "wait-clock")
    ensure_session_ci_wait_schema(conn)
    conn.execute(
        "UPDATE harness_sessions SET turn_posture='waiting' WHERE session_id='wait-clock'"
    )
    body = writes.RecordCiWaitRequest(
        repo="acme/widgets",
        run_id="native-run",
        kind="selection",
        continue_command=OPAQUE,
    )
    assert writes._insert(
        conn, "%s", session_id="wait-clock", project_id=1, body=body, now=MOMENT
    )
    return body


@pytest.mark.parametrize("zone", ZONES)
def test_ci_wait_record_and_received_verdict_preserve_native_clock_null_and_command(
    test_db, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    body = _seed(test_db)
    row = test_db.execute(
        "SELECT created_at,notified_at,continue_command FROM session_ci_run_waits"
    ).fetchone()
    assert isinstance(row[0], datetime) and tuple(row) == (MOMENT, None, OPAQUE)
    assert not writes._insert(
        test_db,
        "%s",
        session_id="wait-clock",
        project_id=1,
        body=body,
        now=MOMENT + timedelta(microseconds=1),
    )
    later = MOMENT + timedelta(microseconds=1)
    assert observer.apply_received_wait(
        test_db,
        session_id="wait-clock",
        run_id="native-run",
        conclusion="success",
        now=later,
    )
    assert not observer.apply_received_wait(
        test_db,
        session_id="wait-clock",
        run_id="native-run",
        conclusion="failure",
        now=later + timedelta(microseconds=1),
    )
    assert tuple(
        test_db.execute(
            "SELECT created_at,notified_at,conclusion,continue_command FROM session_ci_run_waits"
        ).fetchone()
    ) == (MOMENT, later, "success", OPAQUE)


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("delta,checked", [(-1, 0), (0, 1), (1, 1)])
def test_ci_poll_cutoff_is_inclusive_at_exact_native_microsecond(
    test_db, zone, delta, checked
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    _seed(test_db)
    test_db.execute("UPDATE session_ci_run_waits SET read_at=%s", (MOMENT,))
    now = MOMENT + timedelta(seconds=60, microseconds=delta)
    calls = []

    def read_run(*_args):
        calls.append(True)
        return "in_progress", "", ""

    result = observer.observe_pending_ci_runs(
        test_db, [1], now=now, poll_floor_seconds=60, read_run=read_run
    )
    assert result["checked"] == checked and result["errors"] == []
    assert len(calls) == checked
    assert test_db.execute("SELECT read_at FROM session_ci_run_waits").fetchone()[
        0
    ] == (now if checked else MOMENT)


@pytest.mark.parametrize("zone", ZONES)
def test_ci_notice_acceptance_binds_native_read_and_notification_facts(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    _seed(test_db)
    current = MOMENT + timedelta(microseconds=1)
    delivered = []

    def push(_conn, **kwargs):
        delivered.append(kwargs["now"])
        return "delivered"

    monkeypatch.setattr(observer, "push_ci_run_notice", push)
    result = observer.observe_pending_ci_runs(
        test_db, [1], now=current, read_run=lambda *_args: ("completed", "success", "")
    )
    assert result["notified"] == 1 and result["errors"] == []
    assert delivered == [current] and isinstance(delivered[0], datetime)
    assert tuple(
        test_db.execute(
            "SELECT created_at,read_at,notified_at FROM session_ci_run_waits"
        ).fetchone()
    ) == (MOMENT, current, current)


def test_invalid_replacement_clock_refuses_before_superseded_wait_deletion(test_db):
    _seed(test_db)
    body = writes.RecordCiWaitRequest(
        repo="acme/widgets",
        run_id="replacement",
        kind="selection",
        supersedes_run_id="native-run",
    )
    with pytest.raises(InvalidInstant):
        writes._insert(
            test_db,
            "%s",
            session_id="wait-clock",
            project_id=1,
            body=body,
            now=MOMENT.replace(tzinfo=None),
        )
    assert (
        test_db.execute("SELECT run_id FROM session_ci_run_waits").fetchone()[0]
        == "native-run"
    )


@pytest.mark.parametrize("value", ["", "2026-10-09", MOMENT.replace(tzinfo=None)])
def test_invalid_received_clock_refuses_before_any_sql(value):
    with pytest.raises(InvalidInstant):
        observer.apply_received_wait(
            object(),
            session_id="wait-clock",
            run_id="native-run",
            conclusion="success",
            now=value,
        )


def test_malformed_explicit_sqlite_notification_clock_refuses_authority():
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE session_ci_run_waits (id INTEGER PRIMARY KEY, notified_at TEXT)"
        )
        conn.execute("INSERT INTO session_ci_run_waits VALUES (1,'')")
        with pytest.raises(InvalidInstant):
            observer._wait_already_notified(conn, 1)
