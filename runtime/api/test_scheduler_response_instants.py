"""Actual API projections own canonical nullable scheduler clock leaves."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.api.routes import deploy
from yoke_core.api.main_models import FrontierItemModel, ScheduledStepModel
from yoke_core.domain.frontier_types import AdapterCategory, FrontierItem
from yoke_core.domain.scheduler_types import NextStep, ScheduledStep
from yoke_core.domain.scheduler_exceptional import query_exceptional_items

WIRE = "2026-10-09T15:00:00.123456Z"
INSTANT = parse_instant(WIRE)
CLOCKS = (INSTANT, INSTANT.astimezone(timezone(timedelta(hours=5, minutes=45))), None)


@pytest.mark.parametrize("clock", CLOCKS)
def test_frontier_api_projection_formats_native_clock_only(clock):
    item = FrontierItem(
        item_id=7,
        title="opaque title",
        status="implementing",
        priority="high",
        project="opaque project",
        workflow_id="opaque workflow",
        workflow_version_id=1,
        workflow_version=1,
        stage_index=1,
        adapter=AdapterCategory.CONDUCT,
        created_at=clock,
    )
    payload = json.loads(deploy._frontier_item_to_model(item).model_dump_json())
    assert payload["created_at"] == (None if clock is None else WIRE)
    assert payload["item_id"] == "7"
    assert payload["title"] == "opaque title"
    assert item.created_at == (None if clock is None else INSTANT)
    assert FrontierItemModel.model_validate(payload).created_at == payload["created_at"]


@pytest.mark.parametrize("clock", CLOCKS)
def test_scheduler_api_projection_formats_native_clock_only(clock):
    step = ScheduledStep(
        item_id=7,
        title="opaque title",
        status="implementing",
        priority="high",
        workflow_id="opaque workflow",
        workflow_version_id=1,
        workflow_version=1,
        next_step=NextStep.IMPLEMENT,
        created_at=clock,
    )
    payload = json.loads(deploy._scheduled_step_to_model(step).model_dump_json())
    assert payload["created_at"] == (None if clock is None else WIRE)
    assert payload["title"] == "opaque title"
    assert payload["item_id"] == "7"
    assert step.created_at == (None if clock is None else INSTANT)
    assert (
        ScheduledStepModel.model_validate(payload).created_at == payload["created_at"]
    )


@pytest.mark.parametrize(
    "clock",
    [
        "2026-10-09T15:00:00.123456Z",
        "2026-10-09T20:45:00.123456+05:45",
        datetime(2026, 10, 9),
        0,
        False,
    ],
)
def test_scheduled_step_refuses_non_native_clock(clock):
    with pytest.raises(InvalidInstant):
        ScheduledStep(
            item_id=7,
            title="opaque",
            status="failed",
            priority="high",
            workflow_id="opaque",
            workflow_version_id=1,
            workflow_version=1,
            next_step=NextStep.WAIT,
            created_at=clock,
        )


@pytest.mark.parametrize("microsecond", [0, 123456])
@pytest.mark.parametrize("offset", [0, 330, -240])
def test_scheduled_step_normalizes_native_clock_at_actual_api_owner(
    microsecond, offset
):
    expected = datetime(1969, 12, 31, 23, 59, 59, microsecond, tzinfo=timezone.utc)
    supplied = expected.astimezone(timezone(timedelta(minutes=offset)))
    step = ScheduledStep(
        item_id=7,
        title="opaque",
        status="failed",
        priority="high",
        workflow_id="opaque",
        workflow_version_id=1,
        workflow_version=1,
        next_step=NextStep.WAIT,
        created_at=supplied,
    )
    assert step.created_at == expected
    assert step.created_at.tzinfo is timezone.utc
    assert json.loads(deploy._scheduled_step_to_model(step).model_dump_json())[
        "created_at"
    ] == format_instant(expected)


@pytest.mark.parametrize(
    "clock", ["1969-12-31T23:59:59.123456Z", "1970-01-01T05:29:59.123456+05:30", None]
)
def test_exceptional_sqlite_clock_decodes_before_native_step_handoff(clock):
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE workflow_versions (id INTEGER, version INTEGER)")
        conn.execute(
            "CREATE TABLE items (id INTEGER, title TEXT, status TEXT, priority TEXT, project_id INTEGER, workflow_id TEXT, workflow_version_id INTEGER, created_at TEXT, frozen INTEGER)"
        )
        conn.execute("INSERT INTO workflow_versions VALUES (1, 17)")
        conn.execute(
            "INSERT INTO items VALUES (7, '2026-10-09', 'failed', 'high', 1, 'opaque', 1, ?, 0)",
            (clock,),
        )
        item = query_exceptional_items(conn, [1])[0]
    expected = None if clock is None else parse_instant(clock)
    assert item["created_at"] == expected
    assert item["title"] == "2026-10-09"
    assert item["workflow_version"] == 17
    if expected is not None:
        assert isinstance(item["created_at"], datetime)
        assert item["created_at"].tzinfo is timezone.utc
    step = ScheduledStep(
        item_id=item["id"],
        title=item["title"],
        status=item["status"],
        priority=item["priority"],
        workflow_id=item["workflow_id"],
        workflow_version_id=item["workflow_version_id"],
        workflow_version=item["workflow_version"],
        next_step=NextStep.WAIT,
        created_at=item["created_at"],
    )
    assert step.created_at == expected


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
@pytest.mark.parametrize("microsecond", [0, 123456])
def test_exceptional_postgres_clock_remains_native_through_api(zone, microsecond):
    from runtime.api.fixtures.native_instant_database import blank_database

    expected = datetime(1969, 12, 31, 23, 59, 59, microsecond, tzinfo=timezone.utc)
    supplied = expected.astimezone(timezone(timedelta(minutes=330)))
    with blank_database() as conn:
        conn.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
        conn.execute("CREATE TABLE workflow_versions (id INTEGER, version INTEGER)")
        conn.execute(
            "CREATE TABLE items (id INTEGER, title TEXT, status TEXT, priority TEXT, project_id INTEGER, workflow_id TEXT, workflow_version_id INTEGER, created_at TIMESTAMPTZ, frozen INTEGER)"
        )
        conn.execute("INSERT INTO workflow_versions VALUES (1, 17)")
        conn.execute(
            "INSERT INTO items VALUES (7, '2026-10-09', 'failed', 'high', 1, 'opaque', 1, %s, 0)",
            (supplied,),
        )
        item = query_exceptional_items(conn, [1])[0]
        assert conn.execute("SHOW TimeZone").fetchone()[0] == zone
        stored = conn.execute("SELECT created_at FROM items").fetchone()[0]
        assert isinstance(stored, datetime) and stored.tzinfo is not None
        assert stored == expected
    assert item["created_at"] == expected
    assert item["created_at"].tzinfo is timezone.utc
    step = ScheduledStep(
        item_id=item["id"],
        title=item["title"],
        status=item["status"],
        priority=item["priority"],
        workflow_id=item["workflow_id"],
        workflow_version_id=item["workflow_version_id"],
        workflow_version=item["workflow_version"],
        next_step=NextStep.WAIT,
        created_at=item["created_at"],
    )
    payload = json.loads(deploy._scheduled_step_to_model(step).model_dump_json())
    assert payload["created_at"] == format_instant(expected)
    assert payload["title"] == "2026-10-09"
