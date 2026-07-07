"""Tests for PNG/JPEG to board-art Emoji conversion.

The sizing, aspect, and palette-matching tests are pure and always run. The
end-to-end decode tests require Pillow to synthesise fixture images and are
skipped (not failed) when it is absent, mirroring the converter's
Pillow-optional decode contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.project_contract.board_art.config import parse_art_config
from yoke_contracts.project_contract.board_art import render_board_art
from yoke_contracts.project_contract.board_art import image_to_emoji as image_art
from yoke_contracts.project_contract.board_art.image_to_emoji import (
    IMAGE_BLOCK_MAX_HEIGHT,
    IMAGE_BLOCK_MAX_WIDTH,
    center_crop_box_for_aspect,
    convert_image_to_emoji_block,
    image_block_max_cells,
    target_emoji_dimensions,
)


def _write_test_image(path: Path, *, fmt: str = "PNG") -> None:
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (4, 2))
    pixels = image.load()
    colors = [
        (225, 40, 40),
        (230, 125, 30),
        (245, 205, 45),
        (245, 245, 245),
        (40, 100, 220),
        (130, 80, 200),
        (75, 165, 75),
        (15, 15, 15),
    ]
    for index, color in enumerate(colors):
        pixels[index % 4, index // 4] = color
    image.save(path, format=fmt)


def test_target_dimensions_stay_within_default_twenty_cell_box() -> None:
    master_map = ["x" * 47 for _ in range(14)]

    width, height, max_cells = target_emoji_dimensions(200, 100, master_map)

    assert max_cells == IMAGE_BLOCK_MAX_WIDTH * IMAGE_BLOCK_MAX_HEIGHT
    assert width <= IMAGE_BLOCK_MAX_WIDTH
    assert height <= IMAGE_BLOCK_MAX_HEIGHT
    assert width * height <= max_cells


def test_default_dimensions_can_exceed_master_map_rows_up_to_twenty() -> None:
    master_map = ["x" * 47 for _ in range(9)]

    width, height, max_cells = target_emoji_dimensions(100, 100, master_map)

    assert width == IMAGE_BLOCK_MAX_WIDTH
    assert height == IMAGE_BLOCK_MAX_HEIGHT
    assert width * height <= max_cells


def test_target_dimensions_can_exceed_master_map_columns_when_configured() -> None:
    master_map = ["x" * 47 for _ in range(20)]

    width, height, max_cells = target_emoji_dimensions(
        60,
        20,
        master_map,
        max_area_ratio=None,
        min_width=IMAGE_BLOCK_MAX_WIDTH,
        max_width=60,
        min_height=IMAGE_BLOCK_MAX_HEIGHT,
        max_height=IMAGE_BLOCK_MAX_HEIGHT,
    )

    assert max_cells == 60 * IMAGE_BLOCK_MAX_HEIGHT
    assert width == 60
    assert height == IMAGE_BLOCK_MAX_HEIGHT


def test_target_dimensions_honor_configurable_bounds() -> None:
    master_map = ["x" * 47 for _ in range(14)]

    width, height, max_cells = target_emoji_dimensions(
        1000,
        100,
        master_map,
        max_area_ratio=0.5,
        min_width=8,
        max_width=20,
        min_height=6,
        max_height=10,
        min_aspect_ratio=1.0,
        max_aspect_ratio=2.0,
    )

    assert 8 <= width <= 20
    assert 6 <= height <= 10
    assert 1.0 <= width / height <= 2.0
    assert width * height <= max_cells


def test_center_crop_box_clips_wide_and_tall_sources_to_aspect_range() -> None:
    assert center_crop_box_for_aspect(
        100,
        20,
        min_aspect_ratio=0.5,
        max_aspect_ratio=2.0,
    ) == (30, 0, 70, 20)
    assert center_crop_box_for_aspect(
        20,
        100,
        min_aspect_ratio=0.5,
        max_aspect_ratio=2.0,
    ) == (0, 30, 20, 70)


def test_saturated_pastels_map_to_universal_pastels_not_neutral() -> None:
    # The hybrid palette reaches pink + light blue; a vivid pastel never
    # collapses to a neutral square.
    assert image_art._nearest_emoji((150, 215, 245)) == "🩵"
    assert image_art._nearest_emoji((240, 165, 205)) == "🩷"


def test_png_image_converts_to_palette_emoji_block(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    image_path = tmp_path / "logo.png"
    _write_test_image(image_path)
    cfg = parse_art_config(str(tmp_path / "board-art"))
    cfg.master_map = ["x" * 10 for _ in range(10)]

    block = convert_image_to_emoji_block(image_path, cfg.master_map)

    assert block.source_format == "PNG"
    assert block.cells <= block.max_cells
    assert block.width == IMAGE_BLOCK_MAX_WIDTH
    assert block.height == 10
    assert "🟥" in block.text
    assert "🟦" in block.text


def test_jpeg_image_converts_against_rendered_board_art(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    board_art = tmp_path / "board-art"
    board_art.write_text(render_board_art("Yoke"), encoding="utf-8")
    cfg = parse_art_config(str(board_art))
    image_path = tmp_path / "logo.jpg"
    _write_test_image(image_path, fmt="JPEG")

    block = convert_image_to_emoji_block(image_path, cfg.master_map)

    assert block.source_format == "JPEG"
    assert block.cells <= block.max_cells
    assert block.max_cells == IMAGE_BLOCK_MAX_WIDTH * IMAGE_BLOCK_MAX_HEIGHT
    assert len(block.text.splitlines()) == block.height


def test_wide_source_is_center_cropped_before_sampling(tmp_path: Path) -> None:
    Image = pytest.importorskip("PIL.Image")
    image_path = tmp_path / "wide.png"
    image = Image.new("RGB", (30, 10), (220, 40, 40))
    pixels = image.load()
    for x in range(10, 20):
        for y in range(10):
            pixels[x, y] = (40, 100, 220)
    image.save(image_path, format="PNG")

    block = convert_image_to_emoji_block(
        image_path,
        ["x" * 10 for _ in range(10)],
        min_aspect_ratio=1.0,
        max_aspect_ratio=1.0,
    )

    assert (block.crop_left, block.crop_top) == (10, 0)
    assert (block.crop_right, block.crop_bottom) == (20, 10)
    # Centre crop isolates the blue band; the universal palette maps it to 🟦.
    assert set(block.text.replace("\n", "")) <= {"🟦"}
