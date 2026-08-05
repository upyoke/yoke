"""Tests for board widgets — pure-function helpers.

Companion files split off by topic:

- ``test_widgets_activity.py`` — rollup-sourced lifetime-activity + streak
- ``test_widgets_renders.py`` — weather, velocity sparkline, age heatmap, workflow badges
- ``test_widgets_badges.py`` — achievement badges, velocity meter, deterministic output

This file holds the pure-function unit tests: sparkline construction,
proportional allocation, project filter SQL, and date range.
"""

from __future__ import annotations

from datetime import datetime, timezone
from yoke_contracts.board.widgets import (
    _allocate_proportional,
    _build_sparkline,
    _date_range,
    _project_filter,
)

UTC = timezone.utc  # datetime.UTC is Python 3.11+; this alias also works on 3.10


# ---------------------------------------------------------------------------
# _build_sparkline
# ---------------------------------------------------------------------------


class TestBuildSparkline:
    def test_empty(self):
        assert _build_sparkline([]) == ""

    def test_all_zeros(self):
        result = _build_sparkline([0, 0, 0])
        assert result == "▁▁▁"

    def test_single_value(self):
        result = _build_sparkline([5])
        assert result == "█"

    def test_ascending(self):
        result = _build_sparkline([0, 1, 2, 3, 4, 5])
        assert len(result) == 6
        assert result[0] == "▁"
        assert result[-1] == "█"

    def test_uniform_nonzero(self):
        result = _build_sparkline([3, 3, 3])
        assert result == "███"

    def test_deterministic(self):
        v = [1, 0, 3, 7, 2, 0, 5, 8, 1, 4, 6, 3, 0, 2]
        assert _build_sparkline(v) == _build_sparkline(v)

    def test_fourteen_day_length(self):
        v = list(range(14))
        result = _build_sparkline(v)
        assert len(result) == 14


# ---------------------------------------------------------------------------
# _allocate_proportional
# ---------------------------------------------------------------------------


class TestAllocateProportional:
    def test_basic(self):
        cells = _allocate_proportional([10, 10], 20, 20)
        assert cells == [10, 10]

    def test_min_one_for_nonzero(self):
        cells = _allocate_proportional([1, 99], 100, 10)
        assert cells[0] >= 1
        assert sum(cells) <= 10

    def test_clamp_to_max(self):
        cells = _allocate_proportional([50, 50, 50], 150, 20)
        assert sum(cells) <= 20

    def test_all_zero(self):
        cells = _allocate_proportional([0, 0, 0], 0, 20)
        assert cells == [0, 0, 0]


# ---------------------------------------------------------------------------
# _project_filter
# ---------------------------------------------------------------------------


class TestProjectFilter:
    def test_all_scope(self):
        assert _project_filter("all") == ("", ())

    def test_scoped(self):
        sql, params = _project_filter("yoke")
        assert "project_id" in sql
        assert "slug = %s" in sql
        assert params == ("yoke",)

    def test_alias(self):
        sql, params = _project_filter("externalwebapp", "e")
        assert "e.project_id" in sql
        assert "slug = %s" in sql
        assert params == ("externalwebapp",)

    def test_scope_values_do_not_change_sql_shape(self):
        first_sql, first_params = _project_filter("yoke")
        second_sql, second_params = _project_filter("it's")
        assert first_sql == second_sql
        assert first_params == ("yoke",)
        assert second_params == ("it's",)
        assert "yoke" not in first_sql
        assert "it's" not in second_sql


# ---------------------------------------------------------------------------
# _date_range
# ---------------------------------------------------------------------------


class TestDateRange:
    def test_length(self):
        dates = _date_range(14)
        assert len(dates) == 14

    def test_order(self):
        dates = _date_range(14)
        assert dates == sorted(dates)

    def test_ends_today_utc(self):
        """The board's day vocabulary is UTC (matches item_activity_days.day);
        a local-date window drops today's rows every evening west of
        Greenwich."""
        dates = _date_range(1)
        assert dates[0] == datetime.now(UTC).date().isoformat()



