"""Image-backed Mixed board-art variant generation.

A Mixed variant whose emoji side is a fixed, image-derived grid (produced by
``yoke board art variant create --image``) paired with a rerollable random
figlet-font rendering of the display name. Kept separate from the core
Mixed-variant generator so the authored modules stay focused and small.
"""

from __future__ import annotations

from typing import Sequence

from yoke_contracts.project_contract.board_art.ascii import (
    _fallback_ascii_art,
    _rank_figlet_fonts,
    _render_ascii_variant,
)
from yoke_contracts.project_contract.board_art.variants import _mixed_detail
from yoke_contracts.project_contract.board_art.render_seed import (
    DEFAULT_VARIANT_MAX_WIDTH,
    BoardArtVariant,
    _fits_header_width,
    _resolve_seed,
    choose_art_word,
)


def _select_random_image_mixed_variant_detail(
    word: str,
    emoji_column: str,
    *,
    seed_text: str,
    attempt: int,
    max_width: int,
    used_fonts: Sequence[str] = (),
) -> BoardArtVariant:
    used_font_set = set(used_fonts)
    for pass_requires_new_font in (True, False):
        for font in _rank_figlet_fonts(
            seed_text, salt="image-mixed-ascii", attempt=attempt,
        ):
            if pass_requires_new_font and font in used_font_set:
                continue
            candidate = _mixed_detail(
                word=word,
                ascii_art=_render_ascii_variant(font, word),
                emoji_column=emoji_column,
                font=font,
                emoji_index=None,
            )
            if _fits_header_width(candidate.text, max_width):
                return candidate

    fallback = _mixed_detail(
        word=word,
        ascii_art=_fallback_ascii_art(word),
        emoji_column=emoji_column,
        font=None,
        emoji_index=None,
    )
    if _fits_header_width(fallback.text, max_width):
        return fallback

    raise ValueError(
        "image-backed Mixed variant does not fit under max width; "
        "increase --max-width or lower the image grid width/area"
    )


def generate_random_image_mixed_variant_detail(
    display_name: str,
    emoji_column: str,
    *,
    slug: str | None = None,
    word: str | None = None,
    seed_text: str | None = None,
    attempt: int = 0,
    max_width: int = DEFAULT_VARIANT_MAX_WIDTH,
    used_fonts: Sequence[str] = (),
) -> BoardArtVariant:
    """Generate a Mixed variant with random ASCII and a fixed image emoji grid.

    ``word`` overrides the auto-chosen project word (onboarding "customize
    text").
    """

    word = word if word is not None else choose_art_word(display_name, slug=slug)
    return _select_random_image_mixed_variant_detail(
        word,
        emoji_column,
        seed_text=_resolve_seed(seed_text),
        attempt=attempt,
        max_width=max_width,
        used_fonts=used_fonts,
    )


__all__ = ["generate_random_image_mixed_variant_detail"]
