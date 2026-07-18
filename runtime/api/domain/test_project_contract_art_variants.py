"""Tests for seeded project board-art variants."""

from __future__ import annotations

from importlib.resources import files as resource_files
from pathlib import Path

import pyfiglet

from yoke_contracts.project_contract.board_art.config import (
    WHITE,
    derive_letter_bounds,
    parse_art_config,
)
from yoke_contracts.project_contract import board_art as art_seed
from yoke_contracts.project_contract.board_art import _data as art_data
from yoke_contracts.project_contract.board_art import (
    ASCII_FIGLET_FONTS,
    ASCII_VARIANT_COUNT,
    CURRENT_YOKE_MASTER_MAP_VISUAL_WIDTH,
    DEFAULT_VARIANT_MAX_WIDTH,
    MIXED_EMOJI_COLUMNS,
    MIXED_VARIANT_COUNT,
    choose_art_word,
    generate_random_ascii_variant,
    generate_random_ascii_variant_detail,
    generate_random_mixed_variant,
    generate_random_mixed_variant_detail,
    render_board_art,
)
from yoke_contracts.project_contract.board_art.variants import (
    _select_random_mixed_variant,
)


def test_mixed_emoji_data_source_uses_standalone_separator_lines() -> None:
    text = (
        resource_files("yoke_contracts.project_contract.board_art.data")
        .joinpath("mixed_emoji_columns.txt")
        .read_text(encoding="utf-8")
    )
    sep = art_data._MIXED_COLUMN_SEP
    separator_lines = [line for line in text.splitlines() if sep in line]

    assert separator_lines
    assert all(line == sep for line in separator_lines)
    assert f"\n{sep}\n" in text


def test_mixed_emoji_parser_accepts_legacy_inline_separator_format() -> None:
    sep = art_data._MIXED_COLUMN_SEP
    legacy = f"🟨\n{sep}⬛\n"
    standalone = f"🟨\n{sep}\n⬛\n"
    expected = ("🟨\n", "⬛\n")

    assert art_data._parse_mixed_emoji_columns(legacy) == expected
    assert art_data._parse_mixed_emoji_columns(standalone) == expected


def _sketch_glyph(grid_lines: list[str], lo: int, hi: int) -> tuple[str, ...]:
    return tuple(
        "".join("X" if cell == WHITE else "." for cell in row[lo:hi + 1])
        for row in grid_lines[1:-1]
    )


def test_master_map_generator_uses_handmade_glyph_style() -> None:
    # Render the YOKE wordmark and pin its hand-drawn master-map glyphs, so a
    # regression in _master_map_lines or the glyph data is caught exactly.
    grid = art_seed._master_map_lines("YOKE")
    bounds = derive_letter_bounds(grid)

    assert len(grid) == 14
    assert len(grid[0]) == 33
    assert bounds == [(1, 7), (9, 15), (17, 23), (25, 31)]
    assert _sketch_glyph(grid, *bounds[0]) == (  # Y
        "XX...XX", "XX...XX", "XX...XX", ".XX.XX.", ".XX.XX.", "..XXX..",
        "...X...", "...X...", "...X...", "...X...", "...X...", "...X...",
    )
    assert _sketch_glyph(grid, *bounds[1]) == (  # O
        ".XXXXX.", "XX...XX", "XX...XX", "XX...XX", "XX...XX", "XX...XX",
        "XX...XX", "XX...XX", "XX...XX", "XX...XX", "XX...XX", ".XXXXX.",
    )
    assert _sketch_glyph(grid, *bounds[2]) == (  # K
        "XX...XX", "XX..XX.", "XX.XX..", "XXXX...", "XXX....", "XXXX...",
        "XX.XX..", "XX..XX.", "XX...XX", "XX...XX", "XX...XX", "XX...XX",
    )
    assert _sketch_glyph(grid, *bounds[3]) == (  # E
        "XXXXXXX", "XX.....", "XX.....", "XX.....", "XX.....", "XXXXXX.",
        "XXXXXX.", "XX.....", "XX.....", "XX.....", "XX.....", "XXXXXXX",
    )


def test_master_map_generator_matches_yoke_wordmark_scale() -> None:
    grid = art_seed._master_map_lines("--YOKE--")

    assert len(grid) == 14
    assert len(grid[0]) == 49
    assert derive_letter_bounds(grid) == [
        (1, 3), (5, 7), (9, 15), (17, 23),
        (25, 31), (33, 39), (41, 43), (45, 47),
    ]


def test_board_art_font_pool_excludes_denied_fonts() -> None:
    available = set(pyfiglet.FigletFont.getFonts())
    assert set(ASCII_FIGLET_FONTS) <= available
    # Denylisted fonts are dropped; the rest of the catalog stays in rotation.
    for denied in (
        "notie_ca", "hills___", "1row", "future_5", "brite",
        "fantasy_", "baz__bil", "grand_pr",
        "lexible_", "ripper!_", "charact3", "charset_", "rockbox_", "skateord", "skateroc",
        "t__of_ap", "tecrvs__", "zig_zag_", "eftichess",
    ):
        assert denied not in ASCII_FIGLET_FONTS
    assert "standard" in ASCII_FIGLET_FONTS
    assert len(ASCII_FIGLET_FONTS) > 100


def test_board_art_ascii_variant_uses_installed_pyfiglet_font(
    tmp_path: Path,
) -> None:
    content = render_board_art("ExternalWebapp")
    target = tmp_path / "board-art"
    target.write_text(content, encoding="utf-8")

    cfg = parse_art_config(str(target))
    rendered_ascii = [
        "\n".join(variant.lines)
        for variant in cfg.ascii_variants
    ]
    expected_ascii, expected_fonts = art_seed._select_ascii_variants(
        "ExternalWebapp", "EXT"
    )
    assert len(rendered_ascii) == ASCII_VARIANT_COUNT
    assert len(set(rendered_ascii)) == ASCII_VARIANT_COUNT
    assert rendered_ascii == expected_ascii
    assert len(expected_fonts) == ASCII_VARIANT_COUNT
    assert set(expected_fonts) <= set(ASCII_FIGLET_FONTS)
    for variant in cfg.ascii_variants:
        assert max(
            art_seed._visual_width(line) for line in variant.lines
        ) <= DEFAULT_VARIANT_MAX_WIDTH


def _variant_contains_emoji_column(
    variant_lines: list[str],
    emoji_column: str,
) -> bool:
    expected_lines = emoji_column.splitlines()
    expected_index = 0
    for line in variant_lines:
        if (
            expected_index < len(expected_lines)
            and line.endswith(expected_lines[expected_index])
        ):
            expected_index += 1
    return expected_index == len(expected_lines)


def test_board_art_mixed_variants_sample_current_yoke_emoji_columns(
    tmp_path: Path,
) -> None:
    content = render_board_art("ExternalWebapp")
    target = tmp_path / "board-art"
    target.write_text(content, encoding="utf-8")

    cfg = parse_art_config(str(target))
    assert len(cfg.mixed_variants) == MIXED_VARIANT_COUNT
    matched_columns: set[str] = set()
    for variant in cfg.mixed_variants:
        assert max(
            art_seed._visual_width(line) for line in variant.lines
        ) <= DEFAULT_VARIANT_MAX_WIDTH
        matches = [
            column for column in MIXED_EMOJI_COLUMNS
            if _variant_contains_emoji_column(variant.lines, column)
        ]
        assert matches, "Mixed variant must reuse an extracted emoji column"
        matched_columns.add(matches[0])
    assert len(matched_columns) == MIXED_VARIANT_COUNT


def test_mixed_variant_rejects_fonts_that_only_fit_after_figlet_wrapping() -> None:
    wide_font = "blocks"
    wide_ascii = art_seed._render_ascii_variant(wide_font, "YOKE")
    assert len(wide_ascii.splitlines()) == 11
    assert art_seed._art_visual_width(wide_ascii) >= (
        CURRENT_YOKE_MASTER_MAP_VISUAL_WIDTH
    )

    selected, mixed_art = _select_random_mixed_variant(
        "YOKE",
        seed_text="force-broadway",
        attempt=0,
        max_width=CURRENT_YOKE_MASTER_MAP_VISUAL_WIDTH,
        used_fonts=[
            font for font in ASCII_FIGLET_FONTS if font != wide_font
        ],
        used_emoji_indexes=[
            index for index in range(len(MIXED_EMOJI_COLUMNS)) if index != 4
        ],
    )

    assert selected[0] is None, "wide font must be rejected instead of wrapped"
    assert ".----------------." not in mixed_art
    assert art_seed._art_visual_width(mixed_art) < (
        CURRENT_YOKE_MASTER_MAP_VISUAL_WIDTH
    )


def test_board_art_does_not_reuse_figlet_fonts_across_seeded_variants() -> None:
    word = choose_art_word("ExternalWebapp")
    ascii_variants, ascii_fonts = art_seed._select_ascii_variants("ExternalWebapp", word)
    mixed_variants, mixed_fonts = art_seed._select_mixed_variants(
        "ExternalWebapp", word, used_fonts=ascii_fonts
    )
    selected_fonts = [*ascii_fonts, *mixed_fonts]

    assert len(ascii_variants) == ASCII_VARIANT_COUNT
    assert len(mixed_variants) == MIXED_VARIANT_COUNT
    assert len(selected_fonts) == ASCII_VARIANT_COUNT + MIXED_VARIANT_COUNT
    assert len(set(selected_fonts)) == len(selected_fonts)


def test_random_board_art_variant_helpers_are_seedable_and_width_bounded() -> None:
    ascii_one = generate_random_ascii_variant(
        "ExternalWebapp", seed_text="demo-seed", attempt=0
    )
    ascii_again = generate_random_ascii_variant(
        "ExternalWebapp", seed_text="demo-seed", attempt=0
    )
    mixed_one = generate_random_mixed_variant(
        "ExternalWebapp", seed_text="demo-seed", attempt=0
    )
    mixed_again = generate_random_mixed_variant(
        "ExternalWebapp", seed_text="demo-seed", attempt=0
    )

    assert ascii_one == ascii_again
    assert mixed_one == mixed_again
    assert art_seed._art_visual_width(ascii_one) <= (
        DEFAULT_VARIANT_MAX_WIDTH
    )
    assert art_seed._art_visual_width(mixed_one) <= (
        DEFAULT_VARIANT_MAX_WIDTH
    )


def test_random_board_art_variant_details_can_reroll_mixed_sides() -> None:
    ascii_detail = generate_random_ascii_variant_detail(
        "ExternalWebapp", seed_text="detail-seed", attempt=0
    )
    mixed = generate_random_mixed_variant_detail(
        "ExternalWebapp", seed_text="detail-seed", attempt=0
    )
    keep_ascii = generate_random_mixed_variant_detail(
        "ExternalWebapp",
        seed_text="detail-seed",
        attempt=1,
        keep_ascii_art=mixed.ascii_art,
        keep_font=mixed.font,
        used_emoji_indexes=[mixed.emoji_index]
        if mixed.emoji_index is not None
        else [],
    )
    keep_emoji = generate_random_mixed_variant_detail(
        "ExternalWebapp",
        seed_text="detail-seed",
        attempt=2,
        keep_emoji_column=mixed.emoji_column,
        keep_emoji_index=mixed.emoji_index,
        used_fonts=[mixed.font] if mixed.font else [],
    )

    assert ascii_detail.kind == "ASCII"
    assert ascii_detail.font in ASCII_FIGLET_FONTS
    assert mixed.kind == "Mixed"
    assert mixed.ascii_art
    assert mixed.emoji_column
    assert keep_ascii.ascii_art == mixed.ascii_art
    assert keep_ascii.emoji_column
    assert keep_emoji.emoji_column == mixed.emoji_column
    assert keep_emoji.ascii_art
    for detail in (ascii_detail, mixed, keep_ascii, keep_emoji):
        assert art_seed._art_visual_width(detail.text) <= (
            DEFAULT_VARIANT_MAX_WIDTH
        )
