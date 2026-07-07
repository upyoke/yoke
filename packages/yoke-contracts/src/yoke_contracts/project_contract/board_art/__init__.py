"""Seed board art for the project-local ``.yoke`` contract.

Public facade for the ``board_art`` package — re-exports the seed renderer and the
variant generators/constants from the sibling modules (config / emoji / ascii /
variants / variants_image / render_seed / _data / image_to_emoji / image_pipeline /
palette / image_decode / config_paths). Callers import from this package surface,
not the deep submodules.
"""

from __future__ import annotations

from yoke_contracts.project_contract.board_art.config import BLACK, WHITE
from yoke_contracts.project_contract.board_art.ascii import (
    _render_ascii_variant,
    _render_ascii_variants,
    _select_ascii_variants,
    generate_random_ascii_variant,
    generate_random_ascii_variant_detail,
)
from yoke_contracts.project_contract.board_art._data import MIXED_EMOJI_COLUMNS
from yoke_contracts.project_contract.board_art.variants_image import (
    generate_random_image_mixed_variant_detail,
)
from yoke_contracts.project_contract.board_art.variants import (
    _render_mixed_variants,
    _select_mixed_variants,
    generate_random_mixed_variant,
    generate_random_mixed_variant_detail,
)
from yoke_contracts.project_contract.board_art.render_seed import (
    ASCII_FIGLET_FONTS,
    ASCII_VARIANT_COUNT,
    CURRENT_YOKE_MASTER_MAP_COLUMNS,
    CURRENT_YOKE_MASTER_MAP_VISUAL_WIDTH,
    DEFAULT_VARIANT_MAX_WIDTH,
    FALLBACK_ART_WORD,
    MAX_ART_WORD_LEN,
    MAX_HEADER_ART_WORD_LEN,
    MIXED_VARIANT_COUNT,
    MIXED_VARIANT_GAP,
    BoardArtVariant,
    _ART_HEADER,
    _art_visual_width,
    _master_map_lines,
    _visual_width,
    choose_art_word,
    normalize_header_art_word,
    normalize_master_map_word,
    resolve_project_art_word,
)


def render_board_art(display_name: str = "", *, slug: str | None = None) -> str:
    """Render seed ``.yoke/board-art`` for a project display name."""

    word = choose_art_word(display_name, slug=slug)
    seed_text = display_name or slug or word

    parts = [
        _ART_HEADER.format(white=WHITE, black=BLACK),
        "## Master Map",
        "",
        "\n".join(_master_map_lines(word)),
    ]

    ascii_variants, selected_fonts = _select_ascii_variants(seed_text, word)
    mixed_variants, _ = _select_mixed_variants(
        seed_text, word, used_fonts=selected_fonts,
    )

    for ascii_art in ascii_variants:
        parts.extend(("", "## ASCII", "", ascii_art))

    for mixed_art in mixed_variants:
        parts.extend(("", "## Mixed", "", mixed_art))

    return "\n".join(parts).rstrip() + "\n"


__all__ = [
    "FALLBACK_ART_WORD",
    "MAX_ART_WORD_LEN",
    "MAX_HEADER_ART_WORD_LEN",
    "ASCII_VARIANT_COUNT",
    "MIXED_VARIANT_COUNT",
    "CURRENT_YOKE_MASTER_MAP_COLUMNS",
    "CURRENT_YOKE_MASTER_MAP_VISUAL_WIDTH",
    "DEFAULT_VARIANT_MAX_WIDTH",
    "ASCII_FIGLET_FONTS",
    "MIXED_EMOJI_COLUMNS",
    "MIXED_VARIANT_GAP",
    "BoardArtVariant",
    "choose_art_word",
    "normalize_header_art_word",
    "normalize_master_map_word",
    "resolve_project_art_word",
    "generate_random_ascii_variant",
    "generate_random_ascii_variant_detail",
    "generate_random_image_mixed_variant_detail",
    "generate_random_mixed_variant",
    "generate_random_mixed_variant_detail",
    "render_board_art",
]
