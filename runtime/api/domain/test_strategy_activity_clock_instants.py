"""Strategy activity retains UTC calendar semantics over native revision clocks."""

from contextlib import nullcontext
from datetime import datetime
import json

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import strategy_doc_surfaces
from yoke_core.domain.handlers.strategy_doc_surface_reads import handle_surface_list

NOW = parse_instant("1970-01-01T12:00:00.123456Z")
CUTOFF = parse_instant("1969-12-31T00:00:00Z")
MIDNIGHT = parse_instant("1970-01-01T00:00:00Z")
CONTENT = "opaque 1969-12-31T23:59:59 content remains unchanged"


class _ReadCapture:
    def __init__(self, conn):
        self._conn = conn
        self.cutoffs = []

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, sql, params=()):
        if "FROM strategy_doc_revisions " in sql and "GROUP BY" in sql:
            self.cutoffs.append(params[1])
        return self._conn.execute(sql, params)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_real_strategy_day_projection_native_cutoff_and_registered_reader(
    test_db, monkeypatch, zone
):
    from yoke_core.domain import db_helpers
    from yoke_core.domain.strategy_docs_schema import record_doc_revision

    monkeypatch.setattr(strategy_doc_surfaces, "utc_now", lambda: NOW)
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    clocks = [
        parse_instant("1969-12-30T23:59:59.999999Z"),
        CUTOFF,
        parse_instant("1970-01-01T05:44:59.999999+05:45"),
        MIDNIGHT,
    ]
    for instant in clocks:
        record_doc_revision(
            test_db,
            1,
            "CLOCK-DOCUMENT",
            CONTENT,
            source_operation="activity-fixture",
            actor_id=None,
            created_at=instant,
        )
    record_doc_revision(
        test_db,
        2,
        "OTHER-DOCUMENT",
        CONTENT,
        source_operation="activity-fixture",
        actor_id=None,
        created_at=MIDNIGHT,
    )
    test_db.commit()
    conn = _ReadCapture(test_db)
    for days, cutoff, expected in (
        (
            2,
            CUTOFF,
            [{"day": "1969-12-31", "writes": 2}, {"day": "1970-01-01", "writes": 1}],
        ),
        (0, MIDNIGHT, [{"day": "1970-01-01", "writes": 1}]),
        (-3, MIDNIGHT, [{"day": "1970-01-01", "writes": 1}]),
    ):
        assert test_db.execute("SHOW TimeZone").fetchone()[0] == zone
        assert (
            strategy_doc_surfaces.strategy_write_activity(conn, 1, days=days)
            == expected
        )
        assert isinstance(conn.cutoffs[-1], datetime)
        assert conn.cutoffs[-1] == cutoff
        assert conn.cutoffs[-1].utcoffset().total_seconds() == 0

    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(conn))
    request = FunctionCallRequest(
        function="strategy.surface.list",
        actor=ActorContext(session_id="activity-reader"),
        target=TargetRef(kind="global", project_id="1"),
        payload={},
    )
    assert test_db.execute("SHOW TimeZone").fetchone()[0] == zone
    outcome = handle_surface_list(request)
    assert outcome.primary_success
    assert outcome.result_payload["writes"] == [
        {"day": "1969-12-30", "writes": 1},
        {"day": "1969-12-31", "writes": 2},
        {"day": "1970-01-01", "writes": 1},
    ]
    json.dumps(outcome.result_payload)
    stored = test_db.execute(
        "SELECT content,created_at FROM strategy_doc_revisions WHERE project_id=1 ORDER BY revision"
    ).fetchall()
    assert [row["created_at"] for row in stored] == clocks
    assert all(row["content"] == CONTENT for row in stored)
