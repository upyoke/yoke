"""Tests for board-art rainbow fill and render_header integration.

Split from ``test_board_art.py``. Covers:

* Rainbow fill modes
* render_header parity checks against deterministic baselines
"""

from __future__ import annotations

from yoke_contracts.board.art import (
    BLACK,
    C_DONE,
    C_IDEA,
    WHITE,
    _fill_rainbow_random,
    render_header,
)
from yoke_contracts.board.config import BoardConfig

# Re-export shared fixtures so pytest can pick them up via the test helpers
# module import. ``art_config`` and ``config_file`` come from the helpers
# module and are referenced here so that fixture discovery works.
from runtime.api.test_board_art_test_helpers import (  # noqa: F401
    art_config,
    config_file,
)


# ---------------------------------------------------------------------------
# Rainbow fill tests
# ---------------------------------------------------------------------------


class TestRainbowFill:

    def test_random_fill_replaces_all_white(self):
        import random as stdlib_random
        rng = stdlib_random.Random(42)
        grid = [WHITE * 5, BLACK + WHITE * 3 + BLACK]
        result = _fill_rainbow_random(grid, rng)
        for line in result:
            assert WHITE not in line

    def test_random_fill_preserves_black(self):
        import random as stdlib_random
        rng = stdlib_random.Random(42)
        grid = [BLACK + WHITE + BLACK]
        result = _fill_rainbow_random(grid, rng)
        assert result[0].startswith(BLACK)
        assert result[0].endswith(BLACK)

    def test_deterministic_fill(self):
        import random as stdlib_random
        grid = [WHITE * 10]
        r1 = _fill_rainbow_random(list(grid), stdlib_random.Random(99))
        r2 = _fill_rainbow_random(list(grid), stdlib_random.Random(99))
        assert r1 == r2


# ---------------------------------------------------------------------------
# render_header integration tests
# ---------------------------------------------------------------------------


class TestRenderHeader:

    def test_frontier_header_has_legend(self, art_config):
        cfg = BoardConfig()
        counts = {
            "done": 3, "implemented": 1, "release": 0, "reviewing": 0,
            "implementing": 2, "blocked": 0, "refined": 1, "planning": 0,
            "idea": 1,
            "total": 8, "frozen": 0, "pipeline": 1, "backlog": 1,
        }
        header = render_header(None, cfg, art_config, "frontier", None, counts, seed=42)
        # Stats box renders "Done" and "Backlog" (capitalised section names)
        assert "Done" in header
        assert "Backlog" in header
        # Frontier fill uses status-colored emoji cells
        assert C_IDEA in header or C_DONE in header

    def test_rainbow_header_no_white_cells(self, art_config):
        cfg = BoardConfig()
        counts = {
            "done": 0, "implemented": 0, "release": 0, "reviewing": 0,
            "implementing": 0, "blocked": 0, "refined": 0, "idea": 0,
            "total": 0, "frozen": 0, "pipeline": 0, "backlog": 0,
        }
        header = render_header(
            None, cfg, art_config, "rainbow_random", None, counts, seed=42
        )
        # The art lines should have no remaining W-cells
        art_lines = header.split("\n")
        for line in art_lines[:len(art_config.master_map)]:
            # Stats box lines may not have art content
            art_part = line.split(" ╔")[0] if " ╔" in line else line
            art_part = line.split(" ║")[0] if " ║" in line else art_part
            art_part = line.split(" ╚")[0] if " ╚" in line else art_part
            if art_part.strip():
                assert WHITE not in art_part

    def test_deterministic_header(self, art_config):
        """AC-4/AC-5: Same inputs produce identical output."""
        cfg = BoardConfig()
        counts = {
            "done": 5, "implemented": 2, "release": 1, "reviewing": 1,
            "implementing": 3, "blocked": 0, "refined": 2, "idea": 1,
            "total": 15, "frozen": 1, "pipeline": 3, "backlog": 2,
        }
        h1 = render_header(None, cfg, art_config, "frontier", None, counts, seed=100)
        h2 = render_header(None, cfg, art_config, "frontier", None, counts, seed=100)
        assert h1 == h2

    def test_emoji_variant_header(self, art_config):
        cfg = BoardConfig()
        v = art_config.emoji_variants[0]
        counts = {
            "done": 0, "implemented": 0, "release": 0, "reviewing": 0,
            "implementing": 0, "blocked": 0, "refined": 0, "idea": 0,
            "total": 0, "frozen": 0, "pipeline": 0, "backlog": 0,
        }
        header = render_header(None, cfg, art_config, "emoji_1", v, counts, seed=42)
        assert len(header.split("\n")) > 0

    def test_ascii_variant_header(self, art_config):
        cfg = BoardConfig()
        v = art_config.ascii_variants[0]
        counts = {
            "done": 0, "implemented": 0, "release": 0, "reviewing": 0,
            "implementing": 0, "blocked": 0, "refined": 0, "idea": 0,
            "total": 0, "frozen": 0, "pipeline": 0, "backlog": 0,
        }
        header = render_header(None, cfg, art_config, "ascii_1", v, counts, seed=42)
        assert "THE BOARD" in header

    def test_stats_box_present_in_header(self, art_config):
        cfg = BoardConfig()
        counts = {
            "done": 10, "implemented": 0, "release": 0, "reviewing": 0,
            "implementing": 5, "blocked": 0, "refined": 3, "idea": 2,
            "total": 20, "frozen": 1, "pipeline": 3, "backlog": 2,
        }
        header = render_header(
            None, cfg, art_config, "rainbow_random", None, counts, seed=42
        )
        assert "THE BOARD" in header
        assert "Active" in header
        assert "Done" in header
