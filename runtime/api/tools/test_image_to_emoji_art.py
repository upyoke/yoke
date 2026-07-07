"""Tests for the image->emoji spike's grid-sizing contract."""
from __future__ import annotations

import pytest

from yoke_contracts.project_contract.board_art.image_pipeline import (
    MASTER_MAP_AREA,
    boost_saturation,
    choose_grid,
    color_distance,
    composite,
    mode_block,
    nearest_emoji,
    PALETTE_HYBRID,
    PALETTE_SQUARES,
    PALETTES,
)

BOUNDS = dict(min_w=8, max_w=40, min_h=6, max_h=20, min_aspect=0.45, max_aspect=2.6)


def test_master_map_area_is_half_default():
    # 47 cols * 14 rows = 658; the -50% default cap is 329.
    assert MASTER_MAP_AREA == 658
    assert int(MASTER_MAP_AREA * 0.5) == 329


def test_respects_area_cap_and_bounds():
    gw, gh = choose_grid(1920, 1080, max_area=211, **BOUNDS)
    assert gw * gh <= 211
    assert BOUNDS["min_w"] <= gw <= BOUNDS["max_w"]
    assert BOUNDS["min_h"] <= gh <= BOUNDS["max_h"]
    assert BOUNDS["min_aspect"] <= gw / gh <= BOUNDS["max_aspect"]


def test_tolerance_zero_is_aspect_faithful():
    # 180x110 -> aspect 1.636; faithful integer grid at this cap is 18x11.
    gw, gh = choose_grid(180, 110, max_area=211, aspect_tolerance=0.0, **BOUNDS)
    assert (gw, gh) == (18, 11)
    assert abs(gw / gh - 180 / 110) < 0.01


def test_tolerance_fills_area_budget():
    faithful = choose_grid(180, 110, max_area=211, aspect_tolerance=0.0, **BOUNDS)
    filled = choose_grid(180, 110, max_area=211, aspect_tolerance=0.10, **BOUNDS)
    # Allowing drift uses at least as much of the budget.
    assert filled[0] * filled[1] >= faithful[0] * faithful[1]
    assert filled[0] * filled[1] <= 211


def test_bigger_budget_grows_block():
    small = choose_grid(180, 110, max_area=105, **BOUNDS)
    big = choose_grid(180, 110, max_area=380, **BOUNDS)
    assert big[0] * big[1] > small[0] * small[1]


def test_panoramic_clamped_not_thin():
    # aspect 6.0 must clamp to max_aspect, never produce a crazy-thin strip.
    gw, gh = choose_grid(1200, 200, max_area=211, **BOUNDS)
    assert gw / gh <= BOUNDS["max_aspect"] + 1e-9


def test_tall_clamped_to_min_aspect():
    gw, gh = choose_grid(200, 1200, max_area=211, **BOUNDS)
    assert gw / gh >= BOUNDS["min_aspect"] - 1e-9


def test_impossible_constraints_raise():
    with pytest.raises(SystemExit):
        choose_grid(100, 100, max_area=10, min_w=8, max_w=40,
                    min_h=6, max_h=20, min_aspect=0.45, max_aspect=2.6)


def test_saturation_rescues_pastel_blue():
    pastel_blue = (160, 214, 242)  # raw, this collapses to white
    assert nearest_emoji(pastel_blue, PALETTE_SQUARES) == "⬜"
    assert nearest_emoji(boost_saturation(pastel_blue, 2.2), PALETTE_SQUARES) == "🟦"
    assert boost_saturation((100, 100, 100), 2.0) == (100, 100, 100)  # gray unchanged


def test_palette_mapping_picks_right_hue():
    assert nearest_emoji((255, 0, 0), PALETTE_SQUARES) == "🟥"
    assert nearest_emoji((10, 10, 10), PALETTE_SQUARES) == "⬛"
    assert nearest_emoji((250, 250, 250), PALETTE_SQUARES) == "⬜"
    assert nearest_emoji((40, 140, 255), PALETTE_SQUARES) == "🟦"
    assert color_distance((0, 0, 0), (0, 0, 0)) == 0


def test_hybrid_palette_reaches_pink_and_light_blue():
    glyphs = {e for e, _ in PALETTE_HYBRID}
    assert {"🩷", "🩵"} <= glyphs
    assert len(PALETTE_HYBRID) == len(PALETTE_SQUARES) + 2
    assert PALETTES["mine"] is PALETTE_SQUARES and PALETTES["hybrid"] is PALETTE_HYBRID
    # pink + light blue are reachable in hybrid, not in the squares-only palette.
    assert nearest_emoji((240, 160, 200), PALETTE_HYBRID) == "🩷"
    assert nearest_emoji((150, 215, 245), PALETTE_HYBRID) == "🩵"
    assert nearest_emoji((240, 160, 200), PALETTE_SQUARES) != "🩷"


def test_composite_transparent_over_white_is_white():
    assert composite((0, 0, 0), 0, (255, 255, 255)) == (255, 255, 255)  # was black
    assert composite((10, 20, 30), 255, (255, 255, 255)) == (10, 20, 30)  # opaque


def test_mode_block_majority_vote_outvotes_minority():
    red, black = (220, 56, 47), (0, 0, 0)
    native = [[red] * 4 for _ in range(4)]
    native[0][0] = native[0][1] = native[0][2] = black  # 3/16 minority
    assert mode_block(native, 1, 1, PALETTE_SQUARES) == "🟥"


def test_mode_block_emits_requested_dimensions():
    native = [[(120, 177, 89)] * 8 for _ in range(8)]
    lines = mode_block(native, 4, 3, PALETTE_SQUARES).splitlines()
    assert len(lines) == 3 and all(len(line) == 4 for line in lines)


def test_dimension_box_caps_square_at_twenty():
    gw, gh = choose_grid(500, 500, max_area=20 * 20, min_w=6, max_w=20,
                         min_h=6, max_h=20, min_aspect=0.45, max_aspect=2.6)
    assert (gw, gh) == (20, 20)
