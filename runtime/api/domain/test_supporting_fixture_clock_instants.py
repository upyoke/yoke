"""Supporting clock fixtures preserve native precision and explicit boundaries."""

from datetime import datetime, timedelta
import sqlite3

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from runtime.api import item_roster_test_support as roster
from runtime.api import sessions_api_test_support as lifecycle
from runtime.api.engines import _doctor_db_test_helpers as doctor
from runtime.api.fixtures import session_holdings as holdings
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.sessions_list_read import list_sessions

MOMENT = parse_instant("2026-10-09T16:11:12.345678+05:45")
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]


def test_supporting_clock_generators_return_native_microseconds(monkeypatch):
    for owner in (roster, lifecycle, doctor, holdings):
        monkeypatch.setattr(owner, "utc_now", lambda: MOMENT)
    assert lifecycle.fresh_now() == MOMENT
    assert holdings.instant_ago(1) == MOMENT - timedelta(minutes=1)
    assert roster.instant_minutes_ago(2) == MOMENT - timedelta(minutes=2)
    assert doctor._instant_offset(microseconds=1) == MOMENT + timedelta(microseconds=1)
    for owner in (roster, lifecycle, doctor, holdings):
        monkeypatch.setattr(owner, "utc_now", lambda: MOMENT.replace(tzinfo=None))
    for generator in (
        lifecycle.fresh_now,
        holdings.instant_ago,
        lambda: roster.instant_minutes_ago(1),
        doctor._instant_offset,
    ):
        with pytest.raises(InvalidInstant):
            generator()


@pytest.mark.parametrize("zone", ZONES)
def test_holdings_seeds_bind_native_clocks_and_project_only_at_output(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    monkeypatch.setattr(holdings, "utc_now", lambda: MOMENT)
    insert_item(test_db, id=7, title="clock fixture")
    holdings.insert_session(test_db, "clock-fixture")
    later = MOMENT + timedelta(microseconds=1)
    holdings.insert_item_claim(
        test_db, "clock-fixture", 7, released_at=format_instant(later)
    )
    steering = holdings.insert_steering_claim(test_db, "clock-fixture")
    holdings.insert_document_lock(
        test_db, "clock-fixture", 1, "MISSION", steering_claim_id=steering
    )
    holdings.insert_lease(
        test_db, session_id="clock-fixture", lease_key="QA_HOST:clock-fixture"
    )
    session = test_db.execute(
        "SELECT offered_at,last_heartbeat,ended_at FROM harness_sessions WHERE session_id='clock-fixture'"
    ).fetchone()
    assert tuple(session) == (MOMENT, MOMENT, None)
    assert isinstance(session[0], datetime)
    rows = test_db.execute(
        "SELECT target_kind,claimed_at,last_heartbeat,released_at FROM work_claims WHERE session_id='clock-fixture'"
    ).fetchall()
    assert len(rows) == 3
    for row in rows:
        assert isinstance(row[1], datetime) and row[1] == row[2] == MOMENT
        assert row[3] == (later if row[0] == "item" else None)
    locked = test_db.execute(
        "SELECT d.updated_at,c.registered_at FROM strategy_docs d JOIN strategy_doc_claims c ON c.project_id=d.project_id AND c.strategy_doc_slug=d.slug WHERE c.owner_session_id='clock-fixture'"
    ).fetchone()
    assert tuple(locked) == (MOMENT, MOMENT)
    previous = list_sessions()[0]["holdings"]["previous"]
    item = next(row for row in previous if row["target_kind"] == "item")
    assert item["released_at"] == format_instant(later)


@pytest.mark.parametrize(
    "invalid", ["", "2026-10-09", "2026-10-09T10:26:12", MOMENT.replace(tzinfo=None), 1]
)
@pytest.mark.parametrize(
    "writer,kwargs,field",
    [
        (holdings.insert_session, {"session_id": "clock-fixture"}, "ended_at"),
        (
            holdings.insert_item_claim,
            {"session_id": "clock-fixture", "item_id": 7},
            "released_at",
        ),
        (
            holdings.insert_steering_claim,
            {"session_id": "clock-fixture"},
            "released_at",
        ),
        (
            holdings.insert_session_path_claim,
            {"session_id": "clock-fixture"},
            "released_at",
        ),
        (
            holdings.insert_lease,
            {"session_id": "clock-fixture", "lease_key": "QA_HOST:clock-fixture"},
            "released_at",
        ),
    ],
)
def test_invalid_holdings_seed_clock_refuses_before_sql(writer, kwargs, field, invalid):
    with pytest.raises(InvalidInstant):
        writer(object(), **kwargs, **{field: invalid})


def test_holdings_sqlite_adapter_formats_declared_clocks_only():
    with sqlite3.connect(":memory:") as conn:
        assert (
            holdings._optional_parameter(conn, MOMENT) == "2026-10-09T10:26:12.345678Z"
        )
        assert holdings._optional_parameter(conn, None) is None


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize(
    "apply_schema,table,columns",
    [
        (
            lifecycle._apply_session_schema,
            "harness_sessions",
            (
                "offered_at",
                "last_heartbeat",
                "ended_at",
                "current_item_set_at",
                "recent_item_recorded_at",
                "last_tool_call_at",
                "episode_started_at",
            ),
        ),
        (
            doctor.apply_make_conn_schema,
            "item_worktrees",
            ("created_at", "updated_at", "released_at"),
        ),
    ],
)
def test_minimal_fixture_schema_retains_native_types_and_nullable_absence(
    tmp_path, zone, apply_schema, table, columns
):
    with init_test_db(tmp_path, apply_schema=apply_schema) as token:
        conn = connect_test_db(token)
        try:
            conn.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
            rows = conn.execute(
                "SELECT column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name=%s AND column_name=ANY(%s)",
                (table, list(columns)),
            ).fetchall()
            assert len(rows) == len(columns)
            assert all(row[1] == "timestamp with time zone" for row in rows)
            optional = "ended_at" if table == "harness_sessions" else "released_at"
            assert next(row[2] for row in rows if row[0] == optional) == "YES"
            if table == "harness_sessions":
                conn.execute(
                    "INSERT INTO harness_sessions (session_id,executor,provider,workspace,project_id,offered_at,last_heartbeat) VALUES ('clock-schema','claude-code','anthropic','/tmp/clock-schema',1,%s,%s)",
                    (MOMENT, MOMENT + timedelta(microseconds=1)),
                )
                row = conn.execute(
                    "SELECT offered_at,last_heartbeat,ended_at FROM harness_sessions WHERE session_id='clock-schema'"
                ).fetchone()
            else:
                conn.execute(
                    "INSERT INTO item_worktrees (id,item_id,branch,lane_role,created_at,updated_at) VALUES (7,7,'clock-schema','implementation',%s,%s)",
                    (MOMENT, MOMENT + timedelta(microseconds=1)),
                )
                row = conn.execute(
                    "SELECT created_at,updated_at,released_at FROM item_worktrees WHERE id=7"
                ).fetchone()
                # Slim health-check fixture rows intentionally permit missing clocks.
                conn.execute("INSERT INTO items (id,title) VALUES (7,'clock-schema')")
                assert (
                    conn.execute("SELECT updated_at FROM items WHERE id=7").fetchone()[
                        0
                    ]
                    is None
                )
            assert tuple(row) == (MOMENT, MOMENT + timedelta(microseconds=1), None)
            assert isinstance(row[0], datetime)
        finally:
            conn.close()
