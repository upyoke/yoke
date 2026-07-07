"""Header rendering tests for yoke_contracts.board.art.

Companion to ``test_art.py``. Covers ``render_header`` end-to-end with
frontier counts and the ``_paste_ascii_with_stats`` alignment helper
that handles mixed-width emoji art beside the ASCII stats box.
"""

from __future__ import annotations

import os

import pytest

from yoke_contracts.board.art import (
    ArtConfig,
    _paste_ascii_with_stats,
    _paste_grid_with_stats,
    parse_art_config,
    render_header,
)
from yoke_contracts.board.config import BoardConfig
from yoke_contracts.board.utils import display_width


class TestRenderHeader:
    """Basic header rendering with frontier counts."""

    def test_frontier_mode_renders(self):
        ac = ArtConfig(master_map=["WKWKWKW"])
        fc = {"done": 3, "implementing": 2, "idea": 1, "total": 6,
              "refined": 0, "blocked": 0, "implemented": 0, "release": 0,
              "reviewing": 0, "frozen": 0, "pipeline": 0, "backlog": 1}
        cfg = BoardConfig()
        header = render_header(
            db=None, config=cfg, art_config=ac,
            mode="frontier", variant=None,
            frontier_counts=fc, seed=42,
        )
        assert header is not None
        assert len(header) > 0

    def test_rainbow_mode_renders(self):
        ac = ArtConfig(master_map=["WKWKWKW"])
        fc = {"total": 0, "done": 0, "implementing": 0, "idea": 0,
              "refined": 0, "blocked": 0, "implemented": 0, "release": 0,
              "reviewing": 0, "frozen": 0, "pipeline": 0, "backlog": 0}
        cfg = BoardConfig()
        header = render_header(
            db=None, config=cfg, art_config=ac,
            mode="rainbow_random", variant=None,
            frontier_counts=fc, seed=42,
        )
        assert header is not None

    def test_deterministic_header(self):
        """Same inputs + seed produce identical header."""
        ac = ArtConfig(master_map=["WKWKWKW", "KWKWKWK"])
        fc = {"done": 5, "implementing": 3, "total": 10, "idea": 2,
              "refined": 0, "blocked": 0, "implemented": 0, "release": 0,
              "reviewing": 0, "frozen": 0, "pipeline": 0, "backlog": 2}
        cfg = BoardConfig()
        h1 = render_header(db=None, config=cfg, art_config=ac,
                           mode="rainbow_random", variant=None,
                           frontier_counts=fc, seed=42)
        h2 = render_header(db=None, config=cfg, art_config=ac,
                           mode="rainbow_random", variant=None,
                           frontier_counts=fc, seed=42)
        assert h1 == h2

    def test_stats_box_uses_section_counts_override(self):
        ac = ArtConfig(master_map=["WKWKWKW"])
        frontier = {"done": 1, "implementing": 0, "total": 1, "idea": 0,
                    "refined": 0, "blocked": 0, "implemented": 0, "release": 0,
                    "reviewing": 0, "frozen": 0, "pipeline": 0, "backlog": 0}
        stats = {"active": 10, "pipeline": 8, "backlog": 36, "done": 1786, "frozen": 15}
        cfg = BoardConfig()
        header = render_header(
            db=None, config=cfg, art_config=ac,
            mode="rainbow_random", variant=None,
            frontier_counts=frontier,
            stats_counts=stats,
            stats_total=50,
            seed=42,
        )
        assert "Active    10" in header
        assert "Pipeline   8" in header
        assert "Backlog   36" in header
        assert "Done    1786" in header
        assert "Frozen    15" in header

    def test_empty_master_map(self):
        """Empty master map should not crash."""
        ac = ArtConfig(master_map=[])
        fc = {"total": 0, "done": 0, "implementing": 0, "idea": 0,
              "refined": 0, "blocked": 0, "implemented": 0, "release": 0,
              "reviewing": 0, "frozen": 0, "pipeline": 0, "backlog": 0}
        cfg = BoardConfig()
        header = render_header(db=None, config=cfg, art_config=ac,
                               mode="frontier", variant=None,
                               frontier_counts=fc, seed=42)
        # May be empty or minimal — just must not crash
        assert isinstance(header, str)


class TestPasteAsciiWithStats:
    """Stats box alignment when art lines contain mixed-width emoji."""

    def test_uniform_width_padding(self):
        """All art lines padded to same display width before stats paste."""
        art = [
            "abc \U0001f449\U0001f3ff\U0001f449\U0001f3fe",  # 4 + 4 = 8
            "abc ❤️❤️",                                        # 4 + 4 = 8
        ]
        stats = [" ║ A", " ║ B"]
        result = _paste_ascii_with_stats(art, stats)
        # Both lines should have identical display width
        w0 = display_width(result[0])
        w1 = display_width(result[1])
        assert w0 == w1

    def test_hearts_vs_pointing_alignment(self):
        """The actual bug: hearts row must align with pointing-emoji rows."""
        # Row with 3 skin-toned pointing emoji
        pointing_row = (
            "TEXT "
            "\U0001f449\U0001f3ff"  # 👉🏿
            "\U0001f449\U0001f3fe"  # 👉🏾
            "\U0001f449\U0001f3fd"  # 👉🏽
        )
        # Row with 1 pointing + 1 heart + 1 pointing (same 3-emoji visual width)
        hearts_row = (
            "TEXT "
            "\U0001f449\U0001f3ff"  # 👉🏿
            "❤️"                    # ❤️
            "\U0001f449\U0001f3fd"  # 👉🏽
        )
        stats = [" ║ Pipeline", " ║ Backlog"]
        result = _paste_ascii_with_stats([pointing_row, hearts_row], stats)
        # Stats box border should start at same column
        w0 = display_width(result[0][:result[0].index("║")])
        w1 = display_width(result[1][:result[1].index("║")])
        assert w0 == w1

    def test_all_config_variants_alignment(self):
        """Parse real config and verify every mixed variant has uniform line widths."""
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "..", "data", "config"
        )
        if not os.path.exists(config_path):
            pytest.skip("config file not found")
        ac = parse_art_config(config_path)
        # Use a unique marker unlikely to appear in art
        marker = "\U0001f4a7"  # 💧
        stats = [f" {marker} Line"] * 7  # 7-line stats box

        for variant in ac.mixed_variants + ac.ascii_variants:
            if not variant.lines:
                continue
            result = _paste_ascii_with_stats(variant.lines, stats)
            widths = set()
            for line in result:
                if marker in line:
                    art_part = line[:line.index(marker)]
                    widths.add(display_width(art_part))
            assert len(widths) <= 1, (
                f"Variant {variant.name!r} has uneven art widths: {widths}"
            )


class TestPasteGridWithStats:
    """Stats box border alignment when the box is taller than the emoji grid."""

    def test_box_taller_than_grid_keeps_border_aligned(self):
        """Rows below the art must still carry the box's left margin.

        Regression: short grids were padded with empty strings, so box rows
        that fell below the art jumped to column 0 and the left border (║/╚)
        went jagged.
        """
        grid = ["XXXXXXXXXX" for _ in range(4)]
        stats = [
            " ╔═ THE BOARD",
            " ║ A",
            " ║ B",
            " ║ C",
            " ║ D",
            " ║ E",
            " ║ F",
            " ╚═",
        ]
        result = _paste_grid_with_stats(list(grid), stats)
        assert len(result) == len(stats)
        # Every box row's left border must start at the same display column.
        border_columns = set()
        for line in result:
            marker = "║" if "║" in line else "╔" if "╔" in line else "╚"
            border_columns.add(display_width(line[: line.index(marker)]))
        assert len(border_columns) == 1, (
            f"Box left border misaligned across rows: {border_columns}"
        )

    def test_box_taller_than_emoji_grid_keeps_border_aligned(self):
        """Same invariant holds for emoji-width grid rows."""
        grid = ["\U0001f7e5\U0001f7e6\U0001f7e9" for _ in range(3)]  # 3 wide emoji
        stats = [f" ║ row{i}" for i in range(8)]
        result = _paste_grid_with_stats(list(grid), stats)
        border_columns = {
            display_width(line[: line.index("║")]) for line in result
        }
        assert len(border_columns) == 1, (
            f"Box left border misaligned across rows: {border_columns}"
        )

    def test_filler_rows_match_emoji_wide_cell_count(self):
        """Filler rows must reproduce the art's wide (emoji) cells.

        Display-width alignment alone is terminal-correct but drifts in editors
        that render emoji wider than two monospace cells (VS Code, GitHub),
        because an all-spaces filler row falls short of emoji-bearing rows.
        The filler must carry the same number of wide cells so the bottom
        border (╚) lands under the side borders (║) in those editors too.
        """
        grid = ["\U0001f7e5\U0001f7e6\U0001f7e9" for _ in range(3)]  # 3 wide emoji
        stats = [f" ║ row{i}" for i in range(7)] + [" ╚═"]
        result = _paste_grid_with_stats(list(grid), stats)

        def wide_cells(line, marker):
            prefix = line[: line.index(marker)]
            return sum(1 for ch in prefix if display_width(ch) >= 2)

        emoji_row_wide = wide_cells(result[0], "║")
        filler_wide = wide_cells(result[-1], "╚")
        assert filler_wide == emoji_row_wide == 3, (
            f"filler wide-cells {filler_wide} != art wide-cells {emoji_row_wide}"
        )

    def test_ascii_only_art_filler_stays_spaces(self):
        """Pure-ASCII art needs no emoji backing — filler stays plain spaces."""
        grid = ["abcdef" for _ in range(3)]
        stats = [f" ║ row{i}" for i in range(7)] + [" ╚═"]
        result = _paste_grid_with_stats(list(grid), stats)
        filler_prefix = result[-1][: result[-1].index("╚")]
        assert all(ch == " " for ch in filler_prefix), (
            f"ASCII filler should be all spaces, got {filler_prefix!r}"
        )
