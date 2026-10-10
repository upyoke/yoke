"""Actual identity-file publishers and routed fixture SQL clock ownership."""

from datetime import datetime
import json

import pytest

from yoke_contracts import timestamps
from yoke_contracts.cursor_session_map import record_conversation_session
from yoke_contracts.process_ancestry import ProcessAnchor
from yoke_contracts.session_identity import record_session_anchor
from runtime.api import routed_ownership_test_helpers as routed
from yoke_core.domain import workflow_registry

WIRE = "2026-10-09T15:00:00.123456Z"
INSTANT = timestamps.parse_instant(WIRE)


def test_identity_file_publishers_keep_microseconds_and_opaque_process_identity(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(timestamps, "utc_now", lambda: INSTANT)
    process_start = "Wed Jun 10 14:05:41 2026"
    anchor = ProcessAnchor(pid=234, start_time=process_start, process_name="sample")
    path = tmp_path / "anchors"
    record = record_session_anchor("sample-session", path, anchor=anchor)
    assert record["registered_at"] == WIRE
    assert record["anchor_start_time"] == process_start
    assert json.loads((path / "234.json").read_text()) == record
    assert record_conversation_session(
        "sample-conversation", "sample-session", tmp_path
    )
    document = json.loads((tmp_path / "sample-conversation.json").read_text())
    assert document == {
        "session_id": "sample-session",
        "conversation_id": "sample-conversation",
        "recorded_at": WIRE,
    }
    # A failed generated clock retains existing bytes through best-effort hooks.
    prior_anchor = (path / "234.json").read_bytes()
    prior_map = (tmp_path / "sample-conversation.json").read_bytes()
    monkeypatch.setattr(timestamps, "utc_now", lambda: datetime(2026, 10, 9))
    assert record_session_anchor("sample-session", path, anchor=anchor) is None
    assert (
        record_conversation_session("sample-conversation", "sample-session", tmp_path)
        is False
    )
    assert (path / "234.json").read_bytes() == prior_anchor
    assert (tmp_path / "sample-conversation.json").read_bytes() == prior_map


@pytest.mark.parametrize("postgres", [True, False])
def test_routed_fixture_binds_native_or_explicit_sqlite_instants(monkeypatch, postgres):
    monkeypatch.setattr(
        routed.db_backend, "connection_is_postgres", lambda conn: postgres
    )
    monkeypatch.setattr(routed, "utc_now", lambda: INSTANT)
    monkeypatch.setattr(
        workflow_registry, "resolve_current_workflow_pin", lambda *args: ("issue", 1)
    )

    class Connection:
        def __init__(self):
            self.writes = []

        def execute(self, sql, params):
            self.writes.append((sql, params))

        def commit(self):
            pass

    conn = Connection()
    routed.seed_item(conn)
    routed.register_live_session(conn, "sample-session")
    seeded = routed._SEED_TS if postgres else timestamps.format_instant(routed._SEED_TS)
    now = INSTANT if postgres else WIRE
    assert conn.writes[0][1][5:7] == (seeded, seeded)
    assert conn.writes[1][1][2:4] == (now, now)
    assert conn.writes[1][1][-1] is None
    routed.register_live_session(conn, "sample-session", current_item_id=1)
    assert conn.writes[-1][1][-1] == now
    assert isinstance(routed._SEED_TS, datetime)
    assert routed._SEED_TS.microsecond == 123456
    before = list(conn.writes)
    monkeypatch.setattr(routed, "utc_now", lambda: datetime(2026, 10, 9))
    with pytest.raises(timestamps.InvalidInstant):
        routed.register_live_session(conn, "refused-session")
    assert conn.writes == before


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_release_gap_fixture_reads_native_session_and_claim_clocks(
    tmp_path, monkeypatch, zone
):
    from runtime.api.fixtures.file_test_db import init_test_db

    instant = timestamps.utc_now().replace(microsecond=123456)
    monkeypatch.setattr(routed, "utc_now", lambda: instant)
    with init_test_db(tmp_path, apply_schema=routed.apply_release_gap_schema) as path:
        conn = routed.make_db(path)
        try:
            conn.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
            routed.build_release_gap_fixture(conn)
            row = conn.execute(
                "SELECT offered_at,last_heartbeat,current_item_set_at FROM harness_sessions "
                "WHERE session_id=%s",
                (routed.SESSION_A,),
            ).fetchone()
            assert all(
                isinstance(value, datetime) and value.tzinfo is not None
                for value in (row[0], row[1])
            )
            assert row[0] == row[1] == instant
            assert row[0].microsecond == 123456
            assert row[2] is None
            claim = conn.execute(
                "SELECT claimed_at,released_at FROM work_claims WHERE session_id=%s",
                (routed.SESSION_A,),
            ).fetchone()
            assert all(
                isinstance(value, datetime) and value.tzinfo is not None
                for value in (claim[0], claim[1])
            )
            assert claim[1] >= claim[0]
        finally:
            conn.close()
