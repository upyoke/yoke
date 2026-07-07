"""Achievement badges + velocity meter + deterministic-output tests.

Companion to ``test_widgets.py``. Covers the milestone badges that
celebrate ``done`` count thresholds, the four-row velocity meter, and
the deterministic regression suite that asserts identical fixture data
produces identical widget output.
"""

from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc

from yoke_contracts.board.config import BoardConfig
from yoke_core.board.db import BoardDB
from yoke_contracts.board.widgets import (
    _streak_tier,
    render_achievement_badges,
    render_age_heatmap,
    render_type_badges,
    render_velocity_meter,
    render_weather,
)
from runtime.api.board.tests.conftest import (
    insert_item_raw,
    insert_projects,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# render_achievement_badges
# ---------------------------------------------------------------------------


class TestRenderAchievementBadges:
    def test_no_badges(self, test_db_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (1, "bug in system", "implementing", "issue", "yoke", 0, now, now),
            (2, "some idea", "idea", "issue", "yoke", 0, now, now),
        ])
        with BoardDB(test_db_path) as db:
            result = render_achievement_badges(db, BoardConfig(), "yoke", tex_done=0)
        assert result is None

    def test_milestone_50(self, test_db_path):
        with BoardDB(test_db_path) as db:
            result = render_achievement_badges(db, BoardConfig(), "yoke", tex_done=55)
        assert result is not None
        assert "50done" in result

    def test_milestone_100(self, test_db_path):
        with BoardDB(test_db_path) as db:
            result = render_achievement_badges(db, BoardConfig(), "yoke", tex_done=150)
        assert result is not None
        assert "100done" in result

    def test_milestone_1k(self, test_db_path):
        with BoardDB(test_db_path) as db:
            result = render_achievement_badges(db, BoardConfig(), "yoke", tex_done=1200)
        assert "1kdone" in result

    def test_milestone_1_5k(self, test_db_path):
        with BoardDB(test_db_path) as db:
            result = render_achievement_badges(db, BoardConfig(), "yoke", tex_done=1700)
        assert "1.5kdone" in result

    def test_milestone_10k_plus(self, test_db_path):
        with BoardDB(test_db_path) as db:
            result = render_achievement_badges(db, BoardConfig(), "yoke", tex_done=12500)
        assert "12kdone" in result

    def test_zero_bugs(self, test_db_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (1, "normal item", "implementing", "issue", "yoke", 0, now, now),
        ])
        with BoardDB(test_db_path) as db:
            result = render_achievement_badges(db, BoardConfig(), "yoke", tex_done=0)
        assert result is not None
        assert "zero-bugs" in result

    def test_inbox_zero(self, test_db_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (1, "active item", "implementing", "issue", "yoke", 0, now, now),
        ])
        with BoardDB(test_db_path) as db:
            result = render_achievement_badges(db, BoardConfig(), "yoke", tex_done=0)
        assert result is not None
        assert "inbox-zero" in result

    def test_bug_in_title_blocks_zero_bugs(self, test_db_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (1, "fix a bug", "implementing", "issue", "yoke", 0, now, now),
        ])
        with BoardDB(test_db_path) as db:
            result = render_achievement_badges(db, BoardConfig(), "yoke", tex_done=0)
        if result is not None:
            assert "zero-bugs" not in result


# ---------------------------------------------------------------------------
# render_velocity_meter
# ---------------------------------------------------------------------------


class TestRenderVelocityMeter:
    def test_returns_four_rows(self, test_db_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (1, "item", "implementing", "issue", "yoke", 0, now, now),
        ])
        with BoardDB(test_db_path) as db:
            result = render_velocity_meter(db, BoardConfig(), "yoke")
        assert result is not None
        assert len(result) == 4

    def test_row_labels(self, test_db_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (1, "item", "implementing", "issue", "yoke", 0, now, now),
        ])
        with BoardDB(test_db_path) as db:
            result = render_velocity_meter(db, BoardConfig(), "yoke")
        assert "120d activity" in result[0]
        assert "120d code" in result[1]
        assert "120d issues" in result[2]
        assert "120d strategy" in result[3]

    def test_sparkline_length(self, test_db_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (1, "item", "implementing", "issue", "yoke", 0, now, now),
        ])
        with BoardDB(test_db_path) as db:
            result = render_velocity_meter(db, BoardConfig(), "yoke")
        for row in result:
            parts = row.split(" ", 2)
            assert len(parts) >= 2
            sparkline = parts[1]
            assert len(sparkline) == 120

    def test_with_repo_root(self, test_db_path, tmp_path):
        now = _now_iso()
        insert_item_raw(test_db_path, [
            (1, "item", "implementing", "issue", "yoke", 0, now, now),
        ])
        insert_projects(test_db_path, [("yoke", str(tmp_path))])
        with BoardDB(test_db_path) as db:
            result = render_velocity_meter(
                db, BoardConfig(), "yoke", repo_root=str(tmp_path),
            )
        assert result is not None
        assert len(result) == 4


# ---------------------------------------------------------------------------
# Deterministic regression: fixture data => fixed output
# ---------------------------------------------------------------------------


class TestDeterministicOutput:
    """Verify that identical fixture data produces identical widget output."""

    def _setup_db(self, test_db_path) -> str:
        now = "2025-06-15T12:00:00"
        insert_item_raw(test_db_path, [
            (1, "epic: board rewrite", "implementing", "epic", "yoke", 0, now, now),
            (2, "fix rendering", "done", "issue", "yoke", 0, now, now),
            (3, "add widget", "idea", "issue", "yoke", 0, now, now),
            (4, "frozen old", "idea", "issue", "yoke", 1, now, now),
        ])
        return test_db_path

    def test_weather_deterministic(self, test_db_path):
        self._setup_db(test_db_path)
        with BoardDB(test_db_path) as db:
            r1 = render_weather(db, BoardConfig(), "yoke")
            r2 = render_weather(db, BoardConfig(), "yoke")
        assert r1 == r2

    def test_type_badges_deterministic(self, test_db_path):
        self._setup_db(test_db_path)
        with BoardDB(test_db_path) as db:
            r1 = render_type_badges(db, BoardConfig(), "yoke")
            r2 = render_type_badges(db, BoardConfig(), "yoke")
        assert r1 == r2

    def test_age_heatmap_deterministic(self, test_db_path):
        self._setup_db(test_db_path)
        with BoardDB(test_db_path) as db:
            r1 = render_age_heatmap(db, BoardConfig(), "yoke")
            r2 = render_age_heatmap(db, BoardConfig(), "yoke")
        assert r1 == r2

    def test_achievement_badges_deterministic(self, test_db_path):
        self._setup_db(test_db_path)
        with BoardDB(test_db_path) as db:
            r1 = render_achievement_badges(db, BoardConfig(), "yoke", tex_done=100)
            r2 = render_achievement_badges(db, BoardConfig(), "yoke", tex_done=100)
        assert r1 == r2


class TestStreakTier:
    """Streak badge snaps to tiers: 1, 5, 10, 20, 30, … 100, 200, 300, …"""

    def test_below_tier_one_returns_zero(self):
        assert _streak_tier(0) == 0
        assert _streak_tier(-3) == 0

    def test_tier_one_band(self):
        # 1..4 → tier 1
        for n in range(1, 5):
            assert _streak_tier(n) == 1, f"streak={n}"

    def test_tier_five_band(self):
        # 5..9 → tier 5
        for n in range(5, 10):
            assert _streak_tier(n) == 5, f"streak={n}"

    def test_decade_bands_below_one_hundred(self):
        # 10..19 → 10, 20..29 → 20, …, 90..99 → 90
        for n in range(10, 100):
            assert _streak_tier(n) == (n // 10) * 10, f"streak={n}"

    def test_hundred_bands(self):
        assert _streak_tier(100) == 100
        assert _streak_tier(199) == 100
        assert _streak_tier(200) == 200
        assert _streak_tier(365) == 300
        assert _streak_tier(999) == 900
