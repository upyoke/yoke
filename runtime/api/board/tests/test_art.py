"""Tests for yoke_contracts.board.art — config parsing + weighted selection.

Companion files:

- ``test_art_render.py`` — header rendering + paste alignment
- ``test_art_celebration.py`` — 100%-done celebration mode
"""

from __future__ import annotations

import textwrap

from yoke_contracts.board.art import (
    ArtConfig,
    ArtVariant,
    parse_art_config,
    select_art,
)
from yoke_contracts.board.config import BoardConfig
from yoke_contracts.project_contract.board_art.config_paths import BOARD_ART_FILENAME


# ---------------------------------------------------------------------------
# Art config parsing
# ---------------------------------------------------------------------------


class TestParseArtConfig:
    """Parsing art sections from config files."""

    def test_empty_file_returns_defaults(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text("")
        ac = parse_art_config(str(cfg_file))
        assert ac.master_map == []
        assert ac.emoji_variants == []
        assert ac.ascii_variants == []
        assert ac.mixed_variants == []

    def test_missing_file_returns_defaults(self, tmp_path):
        ac = parse_art_config(str(tmp_path / "nonexistent"))
        assert isinstance(ac, ArtConfig)

    def test_master_map_parsing(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text(textwrap.dedent("""\
            ## Master Map
            WKWKWKW
            KWKWKWK
        """))
        ac = parse_art_config(str(cfg_file))
        assert len(ac.master_map) == 2
        assert "WKWKWKW" in ac.master_map[0]

    def test_config_path_reads_board_art_sibling(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text("## Master Map\nfrom-config\n")
        (tmp_path / BOARD_ART_FILENAME).write_text(textwrap.dedent("""\
            ## Master Map
            from-board-art

            ## Emoji
            art content
        """))
        ac = parse_art_config(str(cfg_file))
        assert ac.master_map == ["from-board-art"]
        assert ac.emoji_variants[0].lines == ["art content"]

    def test_emoji_variant_parsing(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text(textwrap.dedent("""\
            ## Emoji
            line1
            line2
        """))
        ac = parse_art_config(str(cfg_file))
        assert len(ac.emoji_variants) == 1
        assert ac.emoji_variants[0].name == "Emoji"
        assert len(ac.emoji_variants[0].lines) == 2

    def test_ascii_variant_parsing(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text(textwrap.dedent("""\
            ## ASCII
            /---\\
            |   |
            \\---/
        """))
        ac = parse_art_config(str(cfg_file))
        assert len(ac.ascii_variants) == 1

    def test_mixed_variant_parsing(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text(textwrap.dedent("""\
            ## Mixed
            mix1
            mix2
        """))
        ac = parse_art_config(str(cfg_file))
        assert len(ac.mixed_variants) == 1

    def test_multiple_emoji_variants(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text(textwrap.dedent("""\
            ## Emoji
            variant1

            ## Emoji
            variant2
        """))
        ac = parse_art_config(str(cfg_file))
        assert len(ac.emoji_variants) == 2

    def test_weight_active(self, tmp_path):
        cfg_file = tmp_path / "config"
        cfg_file.write_text(textwrap.dedent("""\
            # weight:42
            ## Emoji
            art content
        """))
        ac = parse_art_config(str(cfg_file))
        assert ac.emoji_variants[0].weight == 42

    def test_weight_disabled_ignored(self, tmp_path):
        """AC-3: ``# weight-disabled:`` lines are NOT treated as active."""
        cfg_file = tmp_path / "config"
        cfg_file.write_text(textwrap.dedent("""\
            # weight-disabled:99
            ## Emoji
            art content
        """))
        ac = parse_art_config(str(cfg_file))
        assert ac.emoji_variants[0].weight == 0

    def test_weight_before_header_boundary(self, tmp_path):
        """Weight only applies to the immediately following section."""
        cfg_file = tmp_path / "config"
        cfg_file.write_text(textwrap.dedent("""\
            # weight:10
            ## Emoji
            first

            ## ASCII
            second
        """))
        ac = parse_art_config(str(cfg_file))
        assert ac.emoji_variants[0].weight == 10
        assert ac.ascii_variants[0].weight == 0


# ---------------------------------------------------------------------------
# Art selection — determinism
# ---------------------------------------------------------------------------


class TestSelectArtDeterminism:
    """AC-2: Deterministic seed produces identical selection."""

    def _make_art_config(self) -> ArtConfig:
        return ArtConfig(
            master_map=["WWWWWWW"],
            emoji_variants=[ArtVariant("Emoji", ["e1"], 0)],
            ascii_variants=[ArtVariant("ASCII", ["a1"], 0)],
            mixed_variants=[ArtVariant("Mixed", ["m1"], 0)],
        )

    def test_same_seed_same_result(self):
        cfg = BoardConfig()
        ac = self._make_art_config()
        r1 = select_art(cfg, ac, seed=42)
        r2 = select_art(cfg, ac, seed=42)
        assert r1 == r2

    def test_different_seeds_may_differ(self):
        cfg = BoardConfig()
        ac = self._make_art_config()
        results = set()
        for s in range(100):
            mode, _ = select_art(cfg, ac, seed=s)
            results.add(mode)
        # With 100 different seeds and 5 buckets, we should get variety
        assert len(results) > 1


class TestSelectArtOverride:
    """art_override config key takes priority."""

    def test_valid_override_rainbow(self):
        cfg = BoardConfig(art_override="rainbow_letters")
        ac = ArtConfig()
        mode, variant = select_art(cfg, ac, seed=42)
        assert mode == "rainbow_letters"
        assert variant is None

    def test_valid_override_frontier(self):
        cfg = BoardConfig(art_override="frontier")
        ac = ArtConfig()
        mode, _ = select_art(cfg, ac, seed=42)
        assert mode == "frontier"

    def test_valid_override_emoji_index(self):
        ac = ArtConfig(emoji_variants=[ArtVariant("E", ["x"], 0)])
        cfg = BoardConfig(art_override="emoji_1")
        mode, variant = select_art(cfg, ac, seed=42)
        assert mode == "emoji_1"
        assert variant is not None

    def test_invalid_override_falls_through(self):
        cfg = BoardConfig(art_override="nonexistent_variant")
        ac = ArtConfig(
            emoji_variants=[ArtVariant("E", ["x"], 0)],
        )
        mode, _ = select_art(cfg, ac, seed=42)
        # Falls through to weighted selection — any valid mode is OK
        assert mode is not None


class TestSelectArtBuckets:
    """Weighted bucket selection."""

    def test_all_weight_zero_fallback(self):
        """Zero-weight config falls through to hardcoded fallback."""
        cfg = BoardConfig(
            art_weight_rainbow=0,
            art_weight_emoji=0,
            art_weight_ascii=0,
            art_weight_mixed=0,
            art_weight_frontier=0,
        )
        ac = ArtConfig(emoji_variants=[ArtVariant("E", ["x"], 0)])
        mode, _ = select_art(cfg, ac, seed=42)
        assert mode is not None

    def test_frontier_only(self):
        """If only frontier has weight, always select frontier."""
        cfg = BoardConfig(
            art_weight_rainbow=0,
            art_weight_emoji=0,
            art_weight_ascii=0,
            art_weight_mixed=0,
            art_weight_frontier=100,
        )
        ac = ArtConfig()
        for s in range(20):
            mode, _ = select_art(cfg, ac, seed=s)
            assert mode == "frontier"

    def test_rainbow_only(self):
        """If only rainbow has weight, always select a rainbow mode."""
        cfg = BoardConfig(
            art_weight_rainbow=100,
            art_weight_emoji=0,
            art_weight_ascii=0,
            art_weight_mixed=0,
            art_weight_frontier=0,
        )
        ac = ArtConfig()
        for s in range(20):
            mode, _ = select_art(cfg, ac, seed=s)
            assert mode.startswith("rainbow_")


class TestSelectArtRainbowSubModes:
    """Rainbow sub-mode selection."""

    def test_equal_weight_covers_all_submodes(self):
        """With enough seeds, all 5 sub-modes should appear."""
        cfg = BoardConfig(art_weight_rainbow=100, art_weight_frontier=0,
                          art_weight_emoji=0, art_weight_ascii=0, art_weight_mixed=0)
        ac = ArtConfig()
        modes = set()
        for s in range(200):
            mode, _ = select_art(cfg, ac, seed=s)
            modes.add(mode)
        expected = {"rainbow_random", "rainbow_letters", "rainbow_halves",
                    "rainbow_gradient", "rainbow_emoji"}
        assert modes == expected

    def test_per_variant_weight_selection(self):
        """Per-variant weights bias selection toward weighted modes."""
        cfg = BoardConfig(
            art_weight_rainbow=100, art_weight_frontier=0,
            art_weight_emoji=0, art_weight_ascii=0, art_weight_mixed=0,
        )
        cfg.rainbow_sub_weights = {"random": 100, "letters": 0, "halves": 0,
                                    "gradient": 0, "emoji": 0}
        cfg.art_weight_rainbow_random = 100
        cfg.art_weight_rainbow_letters = 0
        cfg.art_weight_rainbow_halves = 0
        cfg.art_weight_rainbow_gradient = 0
        cfg.art_weight_rainbow_emoji = 0

        ac = ArtConfig()
        for s in range(50):
            mode, _ = select_art(cfg, ac, seed=s)
            assert mode == "rainbow_random"
