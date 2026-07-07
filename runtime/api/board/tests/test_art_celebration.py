"""Celebration-mode tests for yoke_contracts.board.art.

Companion to ``test_art.py``. Covers the random-emoji celebration that
replaces the normal ``done`` color when the project hits 100% done —
both the low-level helpers (``_fill_progress`` / ``_render_stats_box``)
and the integrated ``render_header`` path.
"""

from __future__ import annotations

from yoke_contracts.board.art import (
    ArtConfig,
    C_DONE,
    CELEBRATION_EMOJIS,
    WHITE,
    _fill_progress,
    _render_stats_box,
    render_header,
)
from yoke_contracts.board.config import BoardConfig


class TestCelebrationMode:
    """Tests for celebration mode — random emoji at 100% done."""

    def _grid_3x3(self):
        """Simple 3-line grid with W-cells for testing."""
        return [f"{WHITE}{WHITE}{WHITE}"] * 3

    def test_fill_progress_celebration_replaces_done(self):
        """AC-1: celebration emoji replaces done color in grid."""
        grid = self._grid_3x3()
        counts = {"done": 9, "total": 9}
        emoji = "\U0001f680"  # 🚀
        result = _fill_progress(grid, counts, celebration=emoji)
        joined = "".join(result)
        assert emoji in joined
        assert C_DONE not in joined

    def test_fill_progress_no_celebration_uses_done(self):
        """AC-5: without celebration, normal done color is used."""
        grid = self._grid_3x3()
        counts = {"done": 9, "total": 9}
        result = _fill_progress(grid, counts)
        joined = "".join(result)
        assert C_DONE in joined

    def test_stats_box_celebration_replaces_done_emoji(self):
        """AC-2: stats box uses celebration emoji for Done row."""
        emoji = "\U0001f389"  # 🎉
        lines = _render_stats_box(
            {"active": 0, "pipeline": 0, "backlog": 0, "done": 100, "frozen": 0},
            100,
            celebration=emoji,
        )
        done_line = [l for l in lines if "Done" in l][0]
        assert emoji in done_line
        assert "\U0001f3c6" not in done_line  # no trophy

    def test_stats_box_no_celebration_uses_check(self):
        """AC-2 inverse: without celebration, the ✅ check is used."""
        lines = _render_stats_box(
            {"active": 1, "pipeline": 0, "backlog": 0, "done": 99, "frozen": 0},
            100,
        )
        done_line = [l for l in lines if "Done" in l][0]
        assert "\u2705" in done_line

    def test_celebration_emoji_pool_size(self):
        """AC-4: at least 10 distinct emojis in the pool."""
        assert len(CELEBRATION_EMOJIS) >= 10
        assert len(set(CELEBRATION_EMOJIS)) >= 10

    def test_render_header_celebration_triggers(self):
        """AC-1/AC-2/AC-3: full render_header uses celebration when all done."""
        art_config = ArtConfig(
            master_map=[f"{WHITE}{WHITE}{WHITE}"] * 14,
        )
        config = BoardConfig()
        config.art_override = "frontier"
        stats = {"active": 0, "pipeline": 0, "backlog": 0, "done": 50, "frozen": 0}
        fc = {
            "done": 50, "implemented": 0, "release": 0, "reviewing": 0,
            "implementing": 0, "blocked": 0, "refined": 0, "planning": 0,
            "idea": 0, "total": 50, "frozen": 0, "pipeline": 0, "backlog": 0,
        }
        header = render_header(
            None, config, art_config, "frontier", None, fc,
            stats_counts=stats, stats_total=50, seed=42,
        )
        # Should NOT contain normal done color — celebration overrides it
        assert C_DONE not in header
        # Should contain a celebration emoji from the pool
        assert any(e in header for e in CELEBRATION_EMOJIS)

    def test_render_header_no_celebration_outside_frontier(self):
        """Inbox-zero celebration is gated on frontier mode — other art modes
        keep the ✅ check on the stats-box Done row even at 100% done."""
        art_config = ArtConfig(
            master_map=[f"{WHITE}{WHITE}{WHITE}"] * 14,
        )
        config = BoardConfig()
        stats = {"active": 0, "pipeline": 0, "backlog": 0, "done": 50, "frozen": 0}
        fc = {
            "done": 50, "implemented": 0, "release": 0, "reviewing": 0,
            "implementing": 0, "blocked": 0, "refined": 0, "planning": 0,
            "idea": 0, "total": 50, "frozen": 0, "pipeline": 0, "backlog": 0,
        }
        header = render_header(
            None, config, art_config, "rainbow_random", None, fc,
            stats_counts=stats, stats_total=50, seed=42,
        )
        # Stats-box Done row keeps the ✅ check; no celebration swap outside frontier.
        done_stats_line = [l for l in header.split("\n") if "Done" in l][0]
        assert "\u2705" in done_stats_line  # ✅ check, not a celebration emoji

    def test_render_header_no_celebration_with_active(self):
        """AC-5: celebration does NOT trigger when active items exist."""
        art_config = ArtConfig(
            master_map=[f"{WHITE}{WHITE}{WHITE}"] * 14,
        )
        config = BoardConfig()
        config.art_override = "frontier"
        stats = {"active": 1, "pipeline": 0, "backlog": 0, "done": 49, "frozen": 0}
        fc = {
            "done": 49, "implemented": 0, "release": 0, "reviewing": 0,
            "implementing": 1, "blocked": 0, "refined": 0, "planning": 0,
            "idea": 0, "total": 50, "frozen": 0, "pipeline": 0, "backlog": 0,
        }
        header = render_header(
            None, config, art_config, "frontier", None, fc,
            stats_counts=stats, stats_total=50, seed=42,
        )
        # Normal done color should appear (no celebration)
        assert C_DONE in header

    def test_celebration_consistent_within_render(self):
        """AC-3: same celebration emoji used in grid, stats Done row, and legend."""
        art_config = ArtConfig(
            master_map=[f"{WHITE}{WHITE}{WHITE}"] * 14,
        )
        config = BoardConfig()
        config.art_override = "frontier"
        stats = {"active": 0, "pipeline": 0, "backlog": 0, "done": 50, "frozen": 0}
        fc = {
            "done": 50, "implemented": 0, "release": 0, "reviewing": 0,
            "implementing": 0, "blocked": 0, "refined": 0, "planning": 0,
            "idea": 0, "total": 50, "frozen": 0, "pipeline": 0, "backlog": 0,
        }
        header = render_header(
            None, config, art_config, "frontier", None, fc,
            stats_counts=stats, stats_total=50, seed=42,
        )
        lines = header.split("\n")
        # Find the Done stats row and the legend "done" row
        done_stats_line = [l for l in lines if "Done" in l][0]
        done_legend_line = [l for l in lines if "done" in l.lower() and "Done" not in l]
        # The celebration emoji in the Done stats row should match the legend
        for emoji in CELEBRATION_EMOJIS:
            if emoji in done_stats_line and "Done" in done_stats_line:
                # This is the chosen celebration emoji — verify it's in the legend too
                assert done_legend_line, "Legend line with 'done' not found"
                assert emoji in done_legend_line[0], (
                    f"Celebration emoji {emoji!r} in stats but not legend"
                )
                break
