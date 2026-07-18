"""Tests for board widgets — pure-function helpers.

Companion files split off by topic:

- ``test_widgets_activity.py`` — rollup-sourced lifetime-activity + streak
- ``test_widgets_renders.py`` — weather, velocity sparkline, age heatmap, type badges
- ``test_widgets_badges.py`` — achievement badges, velocity meter, deterministic output

This file holds the pure-function unit tests: sparkline construction,
proportional allocation, project filter SQL, date range, and shortstat
parser.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

UTC = timezone.utc  # datetime.UTC is Python 3.11+; this alias also works on 3.10

from yoke_contracts.board.widgets import (
    _allocate_proportional,
    _build_sparkline,
    _date_range,
    _parse_shortstat,
    _project_filter,
)


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
        assert _project_filter("all") == ""

    def test_scoped(self):
        result = _project_filter("yoke")
        assert "project_id" in result
        assert "slug = 'yoke'" in result

    def test_alias(self):
        result = _project_filter("externalwebapp", "e")
        assert "e.project_id" in result
        assert "slug = 'externalwebapp'" in result

    def test_escape(self):
        result = _project_filter("it's")
        assert "it''s" in result


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


# ---------------------------------------------------------------------------
# _parse_shortstat
# ---------------------------------------------------------------------------


class TestParseShortstat:
    def test_basic_insertions_and_deletions(self):
        output = " 2 files changed, 10 insertions(+), 5 deletions(-)"
        assert _parse_shortstat(output) == 15

    def test_insertions_only(self):
        output = " 1 file changed, 3 insertions(+)"
        assert _parse_shortstat(output) == 3

    def test_deletions_only(self):
        output = " 1 file changed, 7 deletions(-)"
        assert _parse_shortstat(output) == 7

    def test_empty(self):
        assert _parse_shortstat("") == 0
