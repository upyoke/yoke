"""Convert supplied PNG/JPEG images into board-art emoji blocks.

Engine: the validated board-art converter: Pillow-optional decode with a macOS
``sips`` fallback, majority-vote "mode" downsampling so anti-alias edges are
outvoted, and the universal squares + hybrid-pastel palette. Sizing and aspect
handling are board-aware: the output grid is capped at a fraction of the target
board's master-map area and centre-cropped into the accepted aspect band rather
than distorted.
"""

from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Tuple

from yoke_contracts.project_contract.board_art.palette import (
    IMAGE_EMOJI_PALETTE,
    NEUTRAL_EMOJIS,
    EmojiColor,
)
from yoke_contracts.project_contract.board_art.image_pipeline import (
    DEFAULT_MAX_H as IMAGE_BLOCK_MAX_HEIGHT,
    DEFAULT_MAX_W as IMAGE_BLOCK_MAX_WIDTH,
    PALETTE_HYBRID,
    load_native,
    mode_block,
    nearest_emoji,
)

RGB = Tuple[int, int, int]

IMAGE_BLOCK_FULL_AREA_RATIO = 1.0
IMAGE_BLOCK_MAX_AREA_RATIO: float | None = None
IMAGE_BLOCK_MIN_WIDTH = 4
IMAGE_BLOCK_MIN_HEIGHT = 4
IMAGE_BLOCK_ASPECT_RATIO_CAP = 5.0
IMAGE_BLOCK_MIN_ASPECT_RATIO = 1 / IMAGE_BLOCK_ASPECT_RATIO_CAP
IMAGE_BLOCK_MAX_ASPECT_RATIO = IMAGE_BLOCK_ASPECT_RATIO_CAP
SUPPORTED_IMAGE_FORMATS = frozenset({"JPEG", "PNG"})

# Default converter palette (tuple form the engine consumes): the nine universal
# colour squares plus the two hybrid pastels.
DEFAULT_PALETTE = PALETTE_HYBRID

# Magic-byte signatures for the dependency-free format sniff.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"


@dataclass(frozen=True)
class ImageEmojiBlock:
    """Converted image block plus sizing metadata for CLI/reporting."""

    text: str
    width: int
    height: int
    max_cells: int
    source_width: int
    source_height: int
    crop_left: int
    crop_top: int
    crop_right: int
    crop_bottom: int
    cropped_width: int
    cropped_height: int
    source_format: str

    @property
    def cells(self) -> int:
        return self.width * self.height


def master_map_dimensions(master_map: Sequence[str]) -> Tuple[int, int]:
    """Return ``(rows, cols)`` for the parsed board-art master map."""

    rows = [line for line in master_map if line]
    return len(rows), max((len(line) for line in rows), default=0)


def image_block_max_cells(
    master_map: Sequence[str],
    *,
    max_area_ratio: float = IMAGE_BLOCK_FULL_AREA_RATIO,
) -> int:
    """Return the max image-block cell count from the master-map area."""

    rows, cols = master_map_dimensions(master_map)
    if rows <= 0 or cols <= 0:
        raise ValueError("master map must contain at least one non-empty row")
    if not (0 < max_area_ratio <= 1):
        raise ValueError("max_area_ratio must be greater than 0 and at most 1")
    return max(1, math.floor(rows * cols * max_area_ratio))


def target_emoji_dimensions(
    source_width: int,
    source_height: int,
    master_map: Sequence[str],
    *,
    max_area_ratio: float | None = IMAGE_BLOCK_MAX_AREA_RATIO,
    min_width: int = IMAGE_BLOCK_MIN_WIDTH,
    max_width: int | None = IMAGE_BLOCK_MAX_WIDTH,
    min_height: int = IMAGE_BLOCK_MIN_HEIGHT,
    max_height: int | None = IMAGE_BLOCK_MAX_HEIGHT,
    min_aspect_ratio: float = IMAGE_BLOCK_MIN_ASPECT_RATIO,
    max_aspect_ratio: float = IMAGE_BLOCK_MAX_ASPECT_RATIO,
) -> Tuple[int, int, int]:
    """Choose a board-safe ``(width, height, max_cells)`` for an image."""

    if source_width <= 0 or source_height <= 0:
        raise ValueError("source image dimensions must be positive")

    master_rows, master_cols = master_map_dimensions(master_map)
    _validate_dimension_constraints(
        master_rows=master_rows,
        master_cols=master_cols,
        min_width=min_width,
        max_width=max_width,
        min_height=min_height,
        max_height=max_height,
        min_aspect_ratio=min_aspect_ratio,
        max_aspect_ratio=max_aspect_ratio,
    )
    width_ceiling = max_width if max_width is not None else master_cols
    height_ceiling = max_height if max_height is not None else master_rows
    if max_area_ratio is None:
        max_cells = width_ceiling * height_ceiling
    else:
        max_cells = image_block_max_cells(
            master_map,
            max_area_ratio=max_area_ratio,
        )
    source_ratio = source_width / source_height
    best: Tuple[float, int, int] | None = None
    best_width = 1
    best_height = 1

    for height in range(min_height, height_ceiling + 1):
        row_width_ceiling = min(width_ceiling, max_cells // height)
        for width in range(min_width, row_width_ceiling + 1):
            cells = width * height
            output_ratio = width / height
            if not (min_aspect_ratio <= output_ratio <= max_aspect_ratio):
                continue
            ratio_error = abs(math.log((width / height) / source_ratio))
            unused_penalty = 0.2 * (1 - (cells / max_cells))
            score = ratio_error + unused_penalty
            candidate = (score, -cells, width)
            if best is None or candidate < best:
                best = candidate
                best_width = width
                best_height = height

    if best is None:
        raise ValueError(
            "no output dimensions satisfy the image block constraints; "
            "relax min/max width/height, aspect ratio range, or max area ratio"
        )

    return best_width, best_height, max_cells


def convert_image_to_emoji_block(
    image_path: str | Path,
    master_map: Sequence[str],
    *,
    background_rgb: RGB = (255, 255, 255),
    palette: Sequence[Tuple[str, RGB]] | None = None,
    saturate: float = 1.0,
    max_area_ratio: float | None = IMAGE_BLOCK_MAX_AREA_RATIO,
    min_width: int = IMAGE_BLOCK_MIN_WIDTH,
    max_width: int | None = IMAGE_BLOCK_MAX_WIDTH,
    min_height: int = IMAGE_BLOCK_MIN_HEIGHT,
    max_height: int | None = IMAGE_BLOCK_MAX_HEIGHT,
    min_aspect_ratio: float = IMAGE_BLOCK_MIN_ASPECT_RATIO,
    max_aspect_ratio: float = IMAGE_BLOCK_MAX_ASPECT_RATIO,
    crop_to_aspect: bool = True,
) -> ImageEmojiBlock:
    """Decode a PNG/JPEG image and convert it into an emoji-grid block.

    Transparent pixels composite over ``background_rgb``. The source is
    centre-cropped unless ``crop_to_aspect`` is false, then downsampled.
    """

    path = Path(image_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"image not found: {path}")
    source_format = _sniff_format(path)

    try:
        native = load_native(str(path), bg=background_rgb)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ValueError(f"unreadable image: {path}") from exc
    source_height = len(native)
    source_width = len(native[0]) if source_height else 0
    if source_width <= 0 or source_height <= 0:
        raise ValueError(f"image has no pixels: {path}")

    crop_box = (0, 0, source_width, source_height)
    if crop_to_aspect:
        crop_box = center_crop_box_for_aspect(
            source_width,
            source_height,
            min_aspect_ratio=min_aspect_ratio,
            max_aspect_ratio=max_aspect_ratio,
        )
    left, top, right, bottom = crop_box
    cropped = [row[left:right] for row in native[top:bottom]]
    cropped_width = right - left
    cropped_height = bottom - top

    width, height, max_cells = target_emoji_dimensions(
        cropped_width,
        cropped_height,
        master_map,
        max_area_ratio=max_area_ratio,
        min_width=min_width,
        max_width=max_width,
        min_height=min_height,
        max_height=max_height,
        min_aspect_ratio=min_aspect_ratio,
        max_aspect_ratio=max_aspect_ratio,
    )

    text = mode_block(
        cropped,
        width,
        height,
        palette if palette is not None else DEFAULT_PALETTE,
        saturate=saturate,
    )
    return ImageEmojiBlock(
        text=text,
        width=width,
        height=height,
        max_cells=max_cells,
        source_width=source_width,
        source_height=source_height,
        crop_left=left,
        crop_top=top,
        crop_right=right,
        crop_bottom=bottom,
        cropped_width=cropped_width,
        cropped_height=cropped_height,
        source_format=source_format,
    )


def center_crop_box_for_aspect(
    width: int,
    height: int,
    *,
    min_aspect_ratio: float,
    max_aspect_ratio: float,
) -> Tuple[int, int, int, int]:
    """Return a centered crop box clipped to the accepted aspect band."""

    if width <= 0 or height <= 0:
        raise ValueError("source image dimensions must be positive")
    if min_aspect_ratio <= 0 or max_aspect_ratio <= 0:
        raise ValueError("aspect ratio bounds must be positive")
    if min_aspect_ratio > max_aspect_ratio:
        raise ValueError("min aspect ratio cannot exceed max aspect ratio")

    source_aspect = width / height
    if source_aspect < min_aspect_ratio:
        crop_height = max(1, min(height, round(width / min_aspect_ratio)))
        top = (height - crop_height) // 2
        return (0, top, width, top + crop_height)
    if source_aspect > max_aspect_ratio:
        crop_width = max(1, min(width, round(height * max_aspect_ratio)))
        left = (width - crop_width) // 2
        return (left, 0, left + crop_width, height)
    return (0, 0, width, height)


def _validate_dimension_constraints(
    *,
    master_rows: int,
    master_cols: int,
    min_width: int,
    max_width: int | None,
    min_height: int,
    max_height: int | None,
    min_aspect_ratio: float,
    max_aspect_ratio: float,
) -> None:
    if master_rows <= 0 or master_cols <= 0:
        return
    if min_width <= 0 or min_height <= 0:
        raise ValueError("min width and min height must be positive")
    if max_width is not None and max_width <= 0:
        raise ValueError("max width must be positive when supplied")
    if max_height is not None and max_height <= 0:
        raise ValueError("max height must be positive when supplied")
    if max_width is not None and min_width > max_width:
        raise ValueError("min width cannot be greater than max width")
    if max_height is not None and min_height > max_height:
        raise ValueError("min height cannot be greater than max height")
    if min_aspect_ratio <= 0 or max_aspect_ratio <= 0:
        raise ValueError("aspect ratio bounds must be positive")
    if min_aspect_ratio > max_aspect_ratio:
        raise ValueError("min aspect ratio cannot exceed max aspect ratio")


def _sniff_format(path: Path) -> str:
    """Return ``PNG``/``JPEG`` from magic bytes (dependency-free)."""

    head = path.read_bytes()[:8]
    if head.startswith(_PNG_SIGNATURE):
        return "PNG"
    if head.startswith(_JPEG_SIGNATURE):
        return "JPEG"
    supported = ", ".join(sorted(SUPPORTED_IMAGE_FORMATS))
    raise ValueError(
        f"unsupported image format; expected one of: {supported} ({path})"
    )


def _nearest_emoji(rgb: RGB) -> str:
    """Nearest universal-palette emoji for ``rgb`` (engine redmean matcher)."""

    return nearest_emoji(rgb, DEFAULT_PALETTE)


__all__ = [
    "IMAGE_BLOCK_MAX_AREA_RATIO",
    "IMAGE_BLOCK_ASPECT_RATIO_CAP",
    "IMAGE_BLOCK_MAX_ASPECT_RATIO",
    "IMAGE_BLOCK_FULL_AREA_RATIO",
    "IMAGE_BLOCK_MAX_HEIGHT",
    "IMAGE_BLOCK_MAX_WIDTH",
    "IMAGE_BLOCK_MIN_ASPECT_RATIO",
    "IMAGE_BLOCK_MIN_HEIGHT",
    "IMAGE_BLOCK_MIN_WIDTH",
    "IMAGE_EMOJI_PALETTE",
    "NEUTRAL_EMOJIS",
    "SUPPORTED_IMAGE_FORMATS",
    "EmojiColor",
    "ImageEmojiBlock",
    "center_crop_box_for_aspect",
    "convert_image_to_emoji_block",
    "image_block_max_cells",
    "master_map_dimensions",
    "target_emoji_dimensions",
]
