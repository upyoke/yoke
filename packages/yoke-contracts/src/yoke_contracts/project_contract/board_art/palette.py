"""Universal emoji palette for image-to-board-art conversion.

The palette is the validated board-art set: the nine single-codepoint
``Emoji_Presentation=Yes`` colour squares plus the two hybrid pastels
(``🩷``/``🩵``) for the pink and light-blue hues squares cannot reach. These are
the only glyphs that render identically across Terminal and editors — the same
universality constraint enforced for the canonical board art — so the swatch
RGBs live in one place (the converter engine) and are wrapped here rather than
re-listed, keeping a single source of truth for the colour values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from yoke_contracts.project_contract.board_art.image_pipeline import PALETTE_HYBRID


@dataclass(frozen=True)
class EmojiColor:
    """One emoji swatch in the converter palette."""

    emoji: str
    rgb: Tuple[int, int, int]


# Wrap the engine's (emoji, rgb) tuples so the RGB constants are not duplicated.
IMAGE_EMOJI_PALETTE: Tuple[EmojiColor, ...] = tuple(
    EmojiColor(emoji, rgb) for emoji, rgb in PALETTE_HYBRID
)

# The two achromatic squares; saturated pixels are matched against the
# chromatic remainder so a vivid colour never collapses to black/white.
NEUTRAL_EMOJIS = frozenset({"⬛", "⬜"})


__all__ = [
    "EmojiColor",
    "IMAGE_EMOJI_PALETTE",
    "NEUTRAL_EMOJIS",
]
