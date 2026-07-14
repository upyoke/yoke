"""Render tests for board widgets — weather, velocity sparkline, age heatmap, type badges.

Companion to ``test_widgets.py``. Covers the fixture-DB-driven render
helpers that surface in the board header.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc

from yoke_contracts.board.config import BoardConfig
from yoke_core.board.db import BoardDB
from yoke_contracts.board.widgets import (
    render_age_heatmap,
    render_type_badges,
    render_velocity_sparkline,
    render_weather,
)
from runtime.api.board.tests.conftest import (
    insert_activity_day,
    insert_event,
    insert_item_raw,
    insert_transition,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# render_weather
# ---------------------------------------------------------------------------


class TestRenderWeather:
    def test_clear(self, test_db_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (i, f"item-{i}", "idea", "issue", "yoke", 0, now, now)
            for i in range(5)
        ])
        with BoardDB(test_db_path) as db:
            result = render_weather(db, BoardConfig(), "yoke")
        assert "Clear" in result

    def test_fair(self, test_db_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (i, f"item-{i}", "idea", "issue", "yoke", 0, now, now)
            for i in range(15)
        ])
        with BoardDB(test_db_path) as db:
            result = render_weather(db, BoardConfig(), "yoke")
        assert "Fair" in result

    def test_stormy(self, test_db_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (i, f"item-{i}", "idea", "issue", "yoke", 0, now, now)
            for i in range(30)
        ])
        with BoardDB(test_db_path) as db:
            result = render_weather(db, BoardConfig(), "yoke")
        assert "Stormy" in result

    def test_frozen_excluded(self, test_db_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (i, f"item-{i}", "idea", "issue", "yoke", 1, now, now)
            for i in range(30)
        ])
        with BoardDB(test_db_path) as db:
            result = render_weather(db, BoardConfig(), "yoke")
        assert "Clear" in result

    def test_empty_db(self, test_db_path):
        with BoardDB(test_db_path) as db:
            result = render_weather(db, BoardConfig(), "yoke")
        assert "Clear" in result


# ---------------------------------------------------------------------------
# render_velocity_sparkline
# ---------------------------------------------------------------------------


class TestRenderVelocitySparkline:
    def test_produces_output(self, test_db_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (1, "item-1", "implementing", "issue", "yoke", 0, now, now),
        ])
        with BoardDB(test_db_path) as db:
            result = render_velocity_sparkline(db, BoardConfig(), "yoke")
        assert result is not None
        assert "14d activity" in result

    def test_empty_db(self, test_db_path):
        with BoardDB(test_db_path) as db:
            result = render_velocity_sparkline(db, BoardConfig(), "yoke")
        assert result is not None
        assert "14d activity" in result

    def test_sparkline_reflects_seeded_activity_days(self, test_db_path):
        """The activity bar renders from item_activity_days rows."""
        now = _now_iso()
        today = now[:10]
        insert_item_raw(test_db_path, [
            (1, "item-1", "implementing", "issue", "yoke", 0, now, now),
        ])
        insert_activity_day(test_db_path, "yoke", 1, today)
        with BoardDB(test_db_path) as db:
            result = render_velocity_sparkline(db, BoardConfig(), "yoke")
        assert result is not None
        spark = result.split(" ")[1]
        baseline = "\u2581"
        assert spark[-1] != baseline, (
            "today's seeded activity row must light the last sparkline slot"
        )


# ---------------------------------------------------------------------------
# render_velocity_meter (120d, transitions + activity tables)
# ---------------------------------------------------------------------------


class TestRenderVelocityMeter:
    def test_meter_renders_from_seeded_transitions(self, test_db_path):
        """The 120d meter's activity + delivery rows read the new state
        tables: a task-touch transition lights row 1 and a done
        transition lights row 3 — no events scan involved."""
        from yoke_contracts.board.widgets_velocity_meter import (
            render_velocity_meter,
        )

        now = _now_iso()
        today = now[:10]
        insert_item_raw(test_db_path, [
            (1, "epic-1", "implementing", "epic", "yoke", 0, now, now),
        ])
        insert_activity_day(test_db_path, "yoke", 1, today)
        insert_transition(
            test_db_path, "yoke", 1, "implementing",
            f"{today}T10:00:00Z", task_num=2, from_status="planned",
        )
        insert_transition(
            test_db_path, "yoke", 1, "done",
            f"{today}T11:00:00Z", task_num=2,
            from_status="reviewed-implementation",
        )
        with BoardDB(test_db_path) as db:
            rows = render_velocity_meter(db, BoardConfig(), "yoke")
        assert rows is not None and len(rows) == 4
        baseline = "\u2581"
        act_spark = rows[0].split(" ")[1]
        del_spark = rows[2].split(" ")[1]
        assert "120d activity" in rows[0]
        assert "120d issues" in rows[2]
        assert act_spark[-1] != baseline, (
            "seeded activity + task transition must light today's slot"
        )
        assert del_spark[-1] != baseline, (
            "seeded done transition must light today's delivery slot"
        )

    def test_strategy_row_reads_doc_write_events(self, test_db_path):
        """The strategy row is sourced from the DB write-event stream, not
        git: a StrategyDocReplaced event today lights the last slot, and a
        different project's event does not bleed into the yoke row."""
        from yoke_contracts.board.widgets_velocity_meter import (
            render_velocity_meter,
        )

        now = _now_iso()
        today = now[:10]
        insert_item_raw(test_db_path, [
            (1, "epic-1", "implementing", "epic", "yoke", 0, now, now),
        ])
        insert_event(
            test_db_path, "StrategyDocReplaced", "yoke",
            f"{today}T09:00:00Z", {"old_bytes": 100, "new_bytes": 4200},
        )
        insert_event(
            test_db_path, "StrategyDocCreated", "buzz",
            f"{today}T09:00:00Z", {"new_bytes": 9000},
        )
        with BoardDB(test_db_path) as db:
            rows = render_velocity_meter(db, BoardConfig(), "yoke")
        assert rows is not None and len(rows) == 4
        assert "120d strategy" in rows[3]
        sml_spark = rows[3].split(" ")[1]
        assert sml_spark[-1] != "▁", (
            "a strategy-doc write event today must light the strategy slot"
        )


# ---------------------------------------------------------------------------
# render_age_heatmap
# ---------------------------------------------------------------------------


class TestRenderAgeHeatmap:
    def test_no_items(self, test_db_path):
        with BoardDB(test_db_path) as db:
            result = render_age_heatmap(db, BoardConfig(), "yoke")
        assert result is None

    def test_with_items(self, test_db_path):
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat()
        week_ago = (now_dt - timedelta(days=5)).isoformat()
        insert_item_raw(test_db_path, [
            (1, "fresh", "implementing", "issue", "yoke", 0, now, now),
            (2, "old", "implementing", "issue", "yoke", 0, week_ago, week_ago),
        ])
        with BoardDB(test_db_path) as db:
            result = render_age_heatmap(db, BoardConfig(), "yoke")
        assert result is not None
        assert "age:" in result

    def test_done_excluded(self, test_db_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (1, "done-item", "done", "issue", "yoke", 0, now, now),
        ])
        with BoardDB(test_db_path) as db:
            result = render_age_heatmap(db, BoardConfig(), "yoke")
        assert result is None


# ---------------------------------------------------------------------------
# render_type_badges
# ---------------------------------------------------------------------------


class TestRenderTypeBadges:
    def test_no_items(self, test_db_path):
        with BoardDB(test_db_path) as db:
            result = render_type_badges(db, BoardConfig(), "yoke")
        assert result is None

    def test_with_items(self, test_db_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (1, "a", "implementing", "issue", "yoke", 0, now, now),
            (2, "b", "implementing", "epic", "yoke", 0, now, now),
            (3, "c", "implementing", "issue", "yoke", 0, now, now),
        ])
        with BoardDB(test_db_path) as db:
            result = render_type_badges(db, BoardConfig(), "yoke")
        assert result is not None
        assert "issue:2" in result
        assert "epic:1" in result

    def test_scoped(self, test_db_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (1, "a", "implementing", "issue", "yoke", 0, now, now),
            (2, "b", "implementing", "issue", "buzz", 0, now, now),
        ])
        with BoardDB(test_db_path) as db:
            result = render_type_badges(db, BoardConfig(), "buzz")
        assert result is not None
        assert "issue:1" in result
