"""Image-backed board-art variant selection for the create command."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

from yoke_contracts.project_contract.board_art.config import parse_art_config
from yoke_contracts.project_contract.board_art import (
    BoardArtVariant,
    MIXED_VARIANT_GAP,
    _art_visual_width,
    choose_art_word,
    generate_random_image_mixed_variant_detail,
)
from yoke_contracts.project_contract.board_art.image_to_emoji import (
    IMAGE_BLOCK_MAX_HEIGHT,
    IMAGE_BLOCK_MAX_WIDTH,
    IMAGE_BLOCK_MIN_HEIGHT,
    IMAGE_BLOCK_MIN_WIDTH,
    ImageEmojiBlock,
    convert_image_to_emoji_block,
)
from yoke_contracts.project_contract.board_art.image_decode import image_dimensions


IMAGE_ONLY_VISUAL_WIDTH_THRESHOLD = 100
IMAGE_SQUISH_ASPECT_THRESHOLD = 2.5


def _fallback_ascii_width(display_name: str) -> int:
    word = choose_art_word(display_name)
    return max(12, len(f" {word} "))


def _image_cells_that_fit_variant(display_name: str, max_width: int) -> int:
    available = max_width - _fallback_ascii_width(display_name) - MIXED_VARIANT_GAP
    return max(1, available // 2)


def _image_cells_that_fit_alone(max_width: int) -> int:
    return max(1, max_width // 2)


def _squish_source(source_width: int, source_height: int) -> bool:
    source_aspect = source_width / source_height
    return (
        source_aspect > IMAGE_SQUISH_ASPECT_THRESHOLD
        or source_aspect < 1 / IMAGE_SQUISH_ASPECT_THRESHOLD
    )


def _default_image_constraints(
    *,
    display_name: str,
    max_width: int,
    source_width: int,
    source_height: int,
    min_aspect: float,
    max_aspect: float,
    include_text: bool,
) -> Tuple[int, int, int, int, float, float, bool]:
    image_min_aspect = min_aspect
    image_max_aspect = max_aspect
    source_aspect = source_width / source_height
    should_squish = _squish_source(source_width, source_height)
    if source_width >= source_height:
        image_max_height = IMAGE_BLOCK_MAX_HEIGHT
        desired_width = (
            round(image_max_height * source_aspect)
            if should_squish
            else round(image_max_height * image_max_aspect)
        )
        width_limit = min(
            desired_width,
            round(image_max_height * image_max_aspect),
            _image_cells_that_fit_alone(max_width),
        )
        if include_text:
            width_limit = min(
                width_limit,
                _image_cells_that_fit_variant(display_name, max_width),
            )
        image_max_width = width_limit
        image_min_width = IMAGE_BLOCK_MAX_WIDTH
        image_min_height = image_max_height
        image_max_aspect = image_max_width / image_max_height
    else:
        image_max_width = IMAGE_BLOCK_MAX_WIDTH
        desired_height = (
            round(image_max_width / source_aspect)
            if should_squish
            else round(image_max_width / image_min_aspect)
        )
        image_max_height = min(
            desired_height,
            round(image_max_width / image_min_aspect),
        )
        image_min_width = image_max_width
        image_min_height = IMAGE_BLOCK_MAX_HEIGHT
        image_min_aspect = image_max_width / image_max_height
    return (
        image_min_width,
        image_max_width,
        image_min_height,
        image_max_height,
        image_min_aspect,
        image_max_aspect,
        not should_squish,
    )


def _explicit_image_constraints(
    *,
    max_width: int,
    image_min_width: int | None,
    image_max_width: int | None,
    image_min_height: int | None,
    image_max_height: int | None,
) -> Tuple[int, int, int, int]:
    max_image_width = image_max_width if image_max_width is not None else (
        IMAGE_BLOCK_MAX_WIDTH
    )
    max_image_width = min(max_image_width, _image_cells_that_fit_alone(max_width))
    max_image_height = image_max_height if image_max_height is not None else (
        IMAGE_BLOCK_MAX_HEIGHT
    )
    min_image_width = image_min_width if image_min_width is not None else (
        IMAGE_BLOCK_MIN_WIDTH
    )
    min_image_height = image_min_height if image_min_height is not None else (
        IMAGE_BLOCK_MIN_HEIGHT
    )
    return min_image_width, max_image_width, min_image_height, max_image_height


def _image_only_variant(
    display_name: str, image_text: str, *, word: str | None = None
) -> BoardArtVariant:
    return BoardArtVariant(
        kind="Emoji",
        text=image_text,
        word=word if word is not None else choose_art_word(display_name),
        emoji_column=image_text,
    )


def _convert_image(
    *,
    image_path: Path,
    master_map: list[str],
    max_area_ratio: float | None,
    min_width: int,
    max_width: int,
    min_height: int,
    max_height: int,
    min_aspect: float,
    max_aspect: float,
    crop_to_aspect: bool,
) -> ImageEmojiBlock:
    return convert_image_to_emoji_block(
        image_path,
        master_map,
        max_area_ratio=max_area_ratio,
        min_width=min_width,
        max_width=max_width,
        min_height=min_height,
        max_height=max_height,
        min_aspect_ratio=min_aspect,
        max_aspect_ratio=max_aspect,
        crop_to_aspect=crop_to_aspect,
    )


def build_image_variant(
    *,
    image_path: Path,
    board_art_path: Path | None,
    display_name: str,
    seed_text: str,
    max_width: int,
    image_max_area_ratio: float | None,
    image_min_width: int | None,
    image_max_width: int | None,
    image_min_height: int | None,
    image_max_height: int | None,
    image_min_aspect: float,
    image_max_aspect: float,
    master_map: list[str] | None = None,
    word: str | None = None,
) -> tuple[str, BoardArtVariant, ImageEmojiBlock]:
    source_width, source_height = image_dimensions(str(image_path))
    # The emoji-grid area cap is derived from the master map. Onboarding has no
    # ``.yoke/board-art`` on disk yet, so it passes a synthesized map directly;
    # the CLI path reads it from the checkout's board-art file.
    if master_map is None:
        master_map = parse_art_config(str(board_art_path)).master_map
    default_oriented = (
        image_max_area_ratio is None
        and image_min_width is None
        and image_max_width is None
        and image_min_height is None
        and image_max_height is None
    )
    min_aspect = image_min_aspect
    max_aspect = image_max_aspect
    if default_oriented:
        constraints = _default_image_constraints(
            display_name=display_name,
            max_width=max_width,
            source_width=source_width,
            source_height=source_height,
            min_aspect=min_aspect,
            max_aspect=max_aspect,
            include_text=False,
        )
    else:
        constraints = (*_explicit_image_constraints(
            max_width=max_width,
            image_min_width=image_min_width,
            image_max_width=image_max_width,
            image_min_height=image_min_height,
            image_max_height=image_max_height,
        ), min_aspect, max_aspect, True)

    image_block = _convert_image(
        image_path=image_path,
        master_map=master_map,
        max_area_ratio=image_max_area_ratio,
        min_width=constraints[0],
        max_width=constraints[1],
        min_height=constraints[2],
        max_height=constraints[3],
        min_aspect=constraints[4],
        max_aspect=constraints[5],
        crop_to_aspect=constraints[6],
    )
    if _art_visual_width(image_block.text) > IMAGE_ONLY_VISUAL_WIDTH_THRESHOLD:
        return (
            "Emoji",
            _image_only_variant(display_name, image_block.text, word=word),
            image_block,
        )

    if default_oriented:
        constraints = _default_image_constraints(
            display_name=display_name,
            max_width=max_width,
            source_width=source_width,
            source_height=source_height,
            min_aspect=image_min_aspect,
            max_aspect=image_max_aspect,
            include_text=True,
        )
        image_block = _convert_image(
            image_path=image_path,
            master_map=master_map,
            max_area_ratio=image_max_area_ratio,
            min_width=constraints[0],
            max_width=constraints[1],
            min_height=constraints[2],
            max_height=constraints[3],
            min_aspect=constraints[4],
            max_aspect=constraints[5],
            crop_to_aspect=constraints[6],
        )

    variant = generate_random_image_mixed_variant_detail(
        display_name,
        image_block.text,
        word=word,
        seed_text=seed_text,
        attempt=0,
        max_width=max_width,
    )
    return "Mixed", variant, image_block


__all__ = [
    "IMAGE_ONLY_VISUAL_WIDTH_THRESHOLD",
    "IMAGE_SQUISH_ASPECT_THRESHOLD",
    "build_image_variant",
]
