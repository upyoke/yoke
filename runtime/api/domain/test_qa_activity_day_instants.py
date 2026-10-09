"""QA day summaries use explicit UTC instant bounds on every SQL backend."""

from datetime import timedelta

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import qa_activity_reads as activity


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_daily_summary_keeps_half_open_microsecond_bounds_in_every_server_zone(
    test_db, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    insert_item(test_db, id=8001, title="Day-bound summary")
    start = parse_instant("2026-10-09T00:00:00.000000Z")
    end = start + timedelta(days=1)
    points = [
        start - timedelta(microseconds=1),
        start,
        start + timedelta(microseconds=1),
        end - timedelta(microseconds=1),
        end,
        end + timedelta(microseconds=1),
    ]
    for point in points:
        requirement = insert_qa_requirement(
            test_db,
            item_id=8001,
            method_id="command",
            qa_kind="method_case",
            created_at=point,
        )
        insert_qa_run(
            test_db,
            qa_requirement_id=requirement["id"],
            verdict="pass",
            started_at=point,
            created_at=point,
            completed_at=point,
        )
    test_db.commit()
    result = activity.read_activity(
        test_db, project="yoke", item_ids=[8001], day=start.date()
    )
    assert result["summary"] == {
        "day": "2026-10-09",
        "total": 3,
        "counts": {"passed": 3},
    }


@pytest.mark.parametrize("postgres", [True, False])
def test_summary_binds_native_midnights_or_canonical_sqlite_boundaries(
    monkeypatch, postgres
):
    seen = []
    monkeypatch.setattr(
        activity.db_backend, "connection_is_postgres", lambda conn: postgres
    )
    monkeypatch.setattr(
        activity,
        "query_rows",
        lambda conn, sql, params: seen.append((sql, params)) or [],
    )
    start = parse_instant("2026-10-09T00:00:00.000000Z")
    activity._activity_summary(
        object(), identity=None, deployment_run_id=None, item_ids=None, day=start.date()
    )
    if postgres:
        assert seen[0][1] == (start, start + timedelta(days=1))
    else:
        assert seen[0][1] == (
            "2026-10-09T00:00:00.000000Z",
            "2026-10-10T00:00:00.000000Z",
        )
