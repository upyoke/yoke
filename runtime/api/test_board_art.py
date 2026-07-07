"""Tests for board art config parsing, selection, and small renderers.

Covers:
- ArtConfig/ArtVariant dataclasses
- parse_art_config from project-local board-art format
- Inline # weight: handling
- # weight-disabled: comments are ignored
- Deterministic art selection under fixed seed
- Master-map W-cell fill for frontier mode
- Stats-box rendering

Rainbow fill modes and render_header parity tests live in
``test_board_art_render.py``. Shared fixtures live in
``test_board_art_test_helpers.py``.
"""

from __future__ import annotations

from yoke_contracts.board.art import (
    BLACK,
    C_DONE,
    C_IMPLEMENTING,
    WHITE,
    _fill_progress,
    _render_meter,
    _render_stats_box,
    parse_art_config,
    select_art,
)
from yoke_contracts.board.config import BoardConfig

# Re-export shared fixtures so pytest can pick them up.
from runtime.api.test_board_art_test_helpers import (  # noqa: F401
    MINI_MASTER_MAP,
    art_config,
    config_file,
)


# ---------------------------------------------------------------------------
# parse_art_config tests
# ---------------------------------------------------------------------------


class TestParseArtConfig:
    """Tests for parse_art_config."""

    def test_master_map_parsed(self, art_config):
        assert art_config.master_map == MINI_MASTER_MAP

    def test_emoji_variants_count(self, art_config):
        assert len(art_config.emoji_variants) == 2

    def test_ascii_variants_count(self, art_config):
        assert len(art_config.ascii_variants) == 1

    def test_mixed_variants_count(self, art_config):
        assert len(art_config.mixed_variants) == 1

    def test_emoji_variant_content(self, art_config):
        v = art_config.emoji_variants[0]
        assert len(v.lines) == 3
        assert v.name == "Emoji"

    def test_weight_disabled_ignored(self, art_config):
        """AC-3: # weight-disabled: comments are ignored."""
        v1 = art_config.emoji_variants[0]
        assert v1.weight == 0, "weight-disabled should not set weight"

    def test_weight_active_parsed(self, art_config):
        """AC-2: active # weight: comments set variant weight."""
        v2 = art_config.emoji_variants[1]
        assert v2.weight == 5

    def test_missing_file_returns_defaults(self, tmp_path):
        cfg = parse_art_config(str(tmp_path / "nonexistent"))
        assert cfg.master_map == []
        assert cfg.emoji_variants == []

    def test_ascii_variant_content(self, art_config):
        v = art_config.ascii_variants[0]
        assert v.lines == ["line one of ascii", "line two of ascii"]
        assert v.weight == 0

    def test_mixed_variant_content(self, art_config):
        v = art_config.mixed_variants[0]
        assert v.lines == ["mixed line one", "mixed line two"]


# ---------------------------------------------------------------------------
# select_art tests
# ---------------------------------------------------------------------------


class TestSelectArt:
    """Tests for select_art."""

    def test_deterministic_with_seed(self, art_config):
        """AC-5: same seed produces same result."""
        cfg = BoardConfig()
        r1 = select_art(cfg, art_config, seed=42)
        r2 = select_art(cfg, art_config, seed=42)
        assert r1 == r2

    def test_different_seeds_may_differ(self, art_config):
        """Different seeds should eventually produce different results."""
        cfg = BoardConfig()
        results = set()
        for seed in range(100):
            mode, _ = select_art(cfg, art_config, seed=seed)
            results.add(mode)
        assert len(results) > 1, "Expected different modes across seeds"

    def test_art_override_respected(self, art_config):
        cfg = BoardConfig(art_override="frontier")
        mode, variant = select_art(cfg, art_config, seed=0)
        assert mode == "frontier"
        assert variant is None

    def test_art_override_emoji(self, art_config):
        cfg = BoardConfig(art_override="emoji_2")
        mode, variant = select_art(cfg, art_config, seed=0)
        assert mode == "emoji_2"
        assert variant is not None
        assert variant.weight == 5

    def test_invalid_override_falls_through(self, art_config):
        cfg = BoardConfig(art_override="nonexistent_99")
        mode, _ = select_art(cfg, art_config, seed=42)
        assert mode != "nonexistent_99"

    def test_frontier_returns_no_variant(self, art_config):
        cfg = BoardConfig(
            art_weight_frontier=100,
            art_weight_rainbow=0,
            art_weight_emoji=0,
            art_weight_ascii=0,
            art_weight_mixed=0,
        )
        mode, variant = select_art(cfg, art_config, seed=0)
        assert mode == "frontier"
        assert variant is None

    def test_zero_weights_fallback(self, art_config):
        cfg = BoardConfig(
            art_weight_rainbow=0,
            art_weight_emoji=0,
            art_weight_ascii=0,
            art_weight_mixed=0,
            art_weight_frontier=0,
        )
        mode, _ = select_art(cfg, art_config, seed=42)
        # Should fall back to defaults and produce a valid mode
        assert mode != ""

    def test_variant_weights_respected(self, art_config):
        """With only emoji bucket and per-variant weights, variant 2 (weight=5) should
        dominate over variant 1 (weight=0)."""
        cfg = BoardConfig(
            art_weight_rainbow=0,
            art_weight_emoji=100,
            art_weight_ascii=0,
            art_weight_mixed=0,
            art_weight_frontier=0,
        )
        counts = {"emoji_1": 0, "emoji_2": 0}
        for seed in range(200):
            mode, _ = select_art(cfg, art_config, seed=seed)
            if mode in counts:
                counts[mode] += 1
        # Variant 1 has weight 0, variant 2 has weight 5
        # With has_weights=True, variant 1 should never be selected
        assert counts["emoji_1"] == 0
        assert counts["emoji_2"] > 0


# ---------------------------------------------------------------------------
# _render_meter tests
# ---------------------------------------------------------------------------


class TestRenderMeter:

    def test_full_meter(self):
        m = _render_meter(10, 10, WHITE, BLACK)
        assert m == WHITE * 10

    def test_empty_meter(self):
        m = _render_meter(0, 10, WHITE, BLACK)
        assert m == BLACK * 10

    def test_half_meter(self):
        m = _render_meter(5, 10, WHITE, BLACK)
        assert m == WHITE * 5 + BLACK * 5

    def test_min_one_for_nonzero(self):
        m = _render_meter(1, 1000, WHITE, BLACK)
        assert m.startswith(WHITE)
        assert m.count(WHITE) >= 1

    def test_zero_total_nonzero_count(self):
        # count > 0 guarantees at least 1 filled cell even when total=0
        m = _render_meter(5, 0, WHITE, BLACK)
        assert m == WHITE + BLACK * 9

    def test_zero_total_zero_count(self):
        m = _render_meter(0, 0, WHITE, BLACK)
        assert m == BLACK * 10


# ---------------------------------------------------------------------------
# _render_stats_box tests
# ---------------------------------------------------------------------------


class TestRenderStatsBox:

    def test_wide_box_has_eight_lines(self):
        counts = {
            "active": 3, "pipeline": 5, "backlog": 10,
            "blocked": 1, "done": 20, "frozen": 2,
        }
        lines = _render_stats_box(counts, total=41)
        assert len(lines) == 8

    def test_narrow_box_has_eight_lines(self):
        counts = {
            "active": 3, "pipeline": 5, "backlog": 10,
            "blocked": 1, "done": 20, "frozen": 2,
        }
        lines = _render_stats_box(counts, total=0)
        assert len(lines) == 8

    def test_wide_box_contains_meters(self):
        counts = {
            "active": 5, "pipeline": 5, "backlog": 5,
            "blocked": 5, "done": 5, "frozen": 5,
        }
        lines = _render_stats_box(counts, total=30)
        # Wide box has six meter rows (Active, Pipeline, Backlog, Blocked,
        # Done, Frozen) after the added the Blocked row.
        meter_lines = [l for l in lines if WHITE in l or BLACK in l]
        assert len(meter_lines) == 6

    def test_title_present(self):
        counts = {"active": 0, "pipeline": 0, "backlog": 0, "done": 0, "frozen": 0}
        lines = _render_stats_box(counts, total=0)
        assert any("THE BOARD" in l for l in lines)


# ---------------------------------------------------------------------------
# _fill_progress tests
# ---------------------------------------------------------------------------


class TestFillProgress:

    def test_all_done_fills_all_green(self):
        grid = [WHITE * 4]
        counts = {"done": 10, "total": 10}
        result = _fill_progress(grid, counts)
        assert WHITE not in result[0]
        assert C_DONE in result[0]

    def test_zero_total_no_change(self):
        grid = [WHITE * 4]
        counts = {"done": 5, "total": 0}
        result = _fill_progress(grid, counts)
        assert result == grid

    def test_proportional_fill(self):
        grid = [WHITE * 10]
        counts = {"done": 5, "implementing": 5, "total": 10}
        result = _fill_progress(grid, counts)
        assert result[0].count(C_DONE) == 5
        assert result[0].count(C_IMPLEMENTING) == 5

    def test_preserves_black_cells(self):
        grid = [BLACK + WHITE + BLACK + WHITE + BLACK]
        counts = {"done": 10, "total": 10}
        result = _fill_progress(grid, counts)
        assert result[0].count(BLACK) == 3
        assert result[0].count(C_DONE) == 2
