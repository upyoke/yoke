"""Fleet seed rows bind native instants while retaining opaque fixture facts."""

from datetime import datetime, timedelta

import pytest

from runtime.api import steering_fleet_seed_rows as rows
from yoke_contracts.timestamps import InvalidInstant, parse_instant

WIRE = "1970-01-01T05:44:59.123456+05:45"
STAMP = parse_instant(WIRE)
OPAQUE = "1969-12-31T23:59:59 unchanged"


class RecordingConnection:
    def __init__(self, conn):
        self._conn = conn
        self.writes = []

    def execute(self, sql, params=()):
        self.writes.append((sql, params))
        return self._conn.execute(sql, params)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_real_seed_rows_bind_native_clocks_in_requested_zone(test_db, zone):
    from runtime.api import steering_fleet_test_helpers as aliases

    for name in (
        "seed_session",
        "seed_tool_call",
        "seed_denial",
        "seed_message",
        "seed_delivery_attempt",
        "seed_relay",
    ):
        assert getattr(aliases, name) is getattr(rows, name)
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    conn = RecordingConnection(test_db)
    rows.seed_session(conn, "seed-session", last_tool_call_at=WIRE, terminated_at=STAMP)
    session_params = conn.writes[-1][1]
    assert all(isinstance(session_params[i], datetime) for i in (5, 6, 10, 12))
    assert session_params[10] == session_params[12] == STAMP
    assert session_params[11] is None
    rows.seed_tool_call(
        conn,
        "seed-session",
        tool_use_id="call",
        started_at=WIRE,
        command_summary=OPAQUE,
    )
    assert conn.writes[-2][1][0] == STAMP
    assert conn.writes[-1][1][3:6] == (STAMP, None, OPAQUE)
    rows.seed_denial(conn, "seed-session", tool_use_id="call", at=STAMP)
    assert conn.writes[-1][1][0] == STAMP
    rows.seed_message(
        conn,
        "message",
        sender=None,
        to="seed-session",
        at=WIRE,
        expires_at=STAMP + timedelta(hours=1),
        routing_snapshot={"opaque": OPAQUE},
    )
    assert conn.writes[-2][1][4:7] == (STAMP, STAMP + timedelta(hours=1), None)
    assert conn.writes[-1][1][6:8] == (STAMP, STAMP)
    rows.seed_delivery_attempt(
        conn,
        "attempt",
        message_id="message",
        to="seed-session",
        result_code=OPAQUE,
        started_at=WIRE,
    )
    assert conn.writes[-1][1][4:7] == (STAMP, STAMP, OPAQUE)
    rows.seed_relay(conn)
    assert all(isinstance(value, datetime) for value in conn.writes[-1][1][4:7])
    assert test_db.execute("SHOW TimeZone").fetchone()[0] == zone
    value = test_db.execute(
        "SELECT created_at,expires_at,cancelled_at FROM session_messages WHERE message_id='message'"
    ).fetchone()
    assert value == (STAMP, STAMP + timedelta(hours=1), None)
    assert test_db.execute(
        "SELECT command_summary,completed_at FROM session_tool_calls WHERE tool_use_id='call'"
    ).fetchone() == (OPAQUE, STAMP)


class NoSQL:
    def execute(self, *_args):
        pytest.fail("invalid supplied fixture clock reached SQL")


@pytest.mark.parametrize(
    "kind,bad",
    [
        (kind, bad)
        for kind in ["session", "tool", "denial", "message", "attempt"]
        for bad in [
            None,
            "",
            "1969-12-31",
            "1969-12-31T23:59:59",
            0,
            datetime(1969, 12, 31),
        ]
        if kind != "session" or bad is not None
    ],
)
def test_bad_seed_clocks_refuse_before_sql(kind, bad):
    conn = NoSQL()
    with pytest.raises(InvalidInstant):
        if kind == "session":
            rows.seed_session(conn, "session", last_tool_call_at=bad)
        elif kind == "tool":
            rows.seed_tool_call(
                conn,
                "session",
                tool_use_id="call",
                started_at=bad,
                command_summary=OPAQUE,
            )
        elif kind == "denial":
            rows.seed_denial(conn, "session", tool_use_id="call", at=bad)
        elif kind == "message":
            rows.seed_message(conn, "message", sender=None, to="session", at=bad)
        else:
            rows.seed_delivery_attempt(
                conn,
                "attempt",
                message_id="message",
                to="session",
                result_code=OPAQUE,
                started_at=bad,
            )
