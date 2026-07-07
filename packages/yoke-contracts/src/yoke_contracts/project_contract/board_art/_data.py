"""Static glyph and emoji-column data for seeded board art."""

from __future__ import annotations

from typing import Dict, Tuple


_ART_GLYPHS: Dict[str, Tuple[str, ...]] = {
    # 5 columns x 7 rows; X = fill-target cell, . = structural cell.
    "A": (".XXX.", "X...X", "X...X", "XXXXX", "X...X", "X...X", "X...X"),
    "B": ("XXXX.", "X...X", "X...X", "XXXX.", "X...X", "X...X", "XXXX."),
    "C": ("XXXXX", "X....", "X....", "X....", "X....", "X....", "XXXXX"),
    "D": ("XXXX.", "X...X", "X...X", "X...X", "X...X", "X...X", "XXXX."),
    "E": ("XXXXX", "X....", "X....", "XXXX.", "X....", "X....", "XXXXX"),
    "F": ("XXXXX", "X....", "X....", "XXXX.", "X....", "X....", "X...."),
    "G": ("XXXXX", "X....", "X....", "X.XXX", "X...X", "X...X", "XXXXX"),
    "H": ("X...X", "X...X", "X...X", "XXXXX", "X...X", "X...X", "X...X"),
    "I": ("XXXXX", "..X..", "..X..", "..X..", "..X..", "..X..", "XXXXX"),
    "J": ("XXXXX", "...X.", "...X.", "...X.", "...X.", "X..X.", "XXXX."),
    "K": ("X...X", "X..X.", "X.X..", "XX...", "X.X..", "X..X.", "X...X"),
    "L": ("X....", "X....", "X....", "X....", "X....", "X....", "XXXXX"),
    "M": ("X...X", "XX.XX", "X.X.X", "X.X.X", "X...X", "X...X", "X...X"),
    "N": ("X...X", "XX..X", "XX..X", "X.X.X", "X..XX", "X..XX", "X...X"),
    "O": ("XXXXX", "X...X", "X...X", "X...X", "X...X", "X...X", "XXXXX"),
    "P": ("XXXXX", "X...X", "X...X", "XXXXX", "X....", "X....", "X...."),
    "Q": ("XXXXX", "X...X", "X...X", "X...X", "X.X.X", "X..X.", "XXX.X"),
    "R": ("XXXXX", "X...X", "X...X", "XXXXX", "X.X..", "X..X.", "X...X"),
    "S": ("XXXXX", "X....", "X....", "XXXXX", "....X", "....X", "XXXXX"),
    "T": ("XXXXX", "..X..", "..X..", "..X..", "..X..", "..X..", "..X.."),
    "U": ("X...X", "X...X", "X...X", "X...X", "X...X", "X...X", "XXXXX"),
    "V": ("X...X", "X...X", "X...X", "X...X", "X...X", ".X.X.", "..X.."),
    "W": ("X...X", "X...X", "X...X", "X.X.X", "X.X.X", "XX.XX", "X...X"),
    "X": ("X...X", "X...X", ".X.X.", "..X..", ".X.X.", "X...X", "X...X"),
    "Y": ("X...X", "X...X", ".X.X.", "..X..", "..X..", "..X..", "..X.."),
    "Z": ("XXXXX", "....X", "...X.", "..X..", ".X...", "X....", "XXXXX"),
    "0": ("XXXXX", "X...X", "X..XX", "X.X.X", "XX..X", "X...X", "XXXXX"),
    "1": ("..X..", ".XX..", "..X..", "..X..", "..X..", "..X..", "XXXXX"),
    "2": ("XXXXX", "....X", "....X", "XXXXX", "X....", "X....", "XXXXX"),
    "3": ("XXXXX", "....X", "....X", ".XXXX", "....X", "....X", "XXXXX"),
    "4": ("X...X", "X...X", "X...X", "XXXXX", "....X", "....X", "....X"),
    "5": ("XXXXX", "X....", "X....", "XXXXX", "....X", "....X", "XXXXX"),
    "6": ("XXXXX", "X....", "X....", "XXXXX", "X...X", "X...X", "XXXXX"),
    "7": ("XXXXX", "....X", "...X.", "..X..", ".X...", ".X...", ".X..."),
    "8": ("XXXXX", "X...X", "X...X", "XXXXX", "X...X", "X...X", "XXXXX"),
    "9": ("XXXXX", "X...X", "X...X", "XXXXX", "....X", "....X", "XXXXX"),
}


def _expand_master_map_glyph(glyph: Tuple[str, ...]) -> Tuple[str, ...]:
    """Scale the compact seed glyphs into the bold master-map cell size."""

    row_map = (0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6)
    col_map = (0, 0, 1, 2, 3, 4, 4)
    return tuple(
        "".join(glyph[row_index][col_index] for col_index in col_map)
        for row_index in row_map
    )


_HAND_DRAWN_MASTER_MAP_GLYPHS: Dict[str, Tuple[str, ...]] = {
    # Exact slices from the original handmade master-map wordmark artwork.
    "A": (
        "..XX..", "..XX..", ".XXXX.", ".XXXX.", ".X..XX", "XX...X",
        "XX...X", "XXXXXX", "XX...X", "XX...X", "XX...X", "XX...X",
    ),
    "D": (
        "XXXXX..", "XX..XX.", "XX...XX", "XX....X", "XX....X", "XX....X",
        "XX....X", "XX....X", "XX....X", "XX...XX", "XX..XX.", "XXXXX..",
    ),
    "N": (
        "XX...XX", "XXX..XX", "XXX..XX", "XX.X.XX", "XX.X.XX", "XX..XXX",
        "XX..XXX", "XX...XX", "XX...XX", "XX...XX", "XX...XX", "XX...XX",
    ),
    "S": (
        ".XXXXX.", "XX...XX", "XX.....", "XX.....", "XX.....", ".XXXX..",
        "....XX.", ".....XX", ".....XX", ".....XX", "XX...XX", ".XXXXX.",
    ),
    "U": (
        "XX...XX", "XX...XX", "XX...XX", "XX...XX", "XX...XX", "XX...XX",
        "XX...XX", "XX...XX", "XX...XX", "XX...XX", "XX...XX", ".XXXXX.",
    ),
    "Y": (
        "XX...XX", "XX...XX", "XX...XX", ".XX.XX.", ".XX.XX.", "..XXX..",
        "...X...", "...X...", "...X...", "...X...", "...X...", "...X...",
    ),
    # Style-matched additions for the Yoke wordmark.
    "E": (
        "XXXXXXX", "XX.....", "XX.....", "XX.....", "XX.....", "XXXXXX.",
        "XXXXXX.", "XX.....", "XX.....", "XX.....", "XX.....", "XXXXXXX",
    ),
    "K": (
        "XX...XX", "XX..XX.", "XX.XX..", "XXXX...", "XXX....", "XXXX...",
        "XX.XX..", "XX..XX.", "XX...XX", "XX...XX", "XX...XX", "XX...XX",
    ),
    "O": (
        ".XXXXX.", "XX...XX", "XX...XX", "XX...XX", "XX...XX", "XX...XX",
        "XX...XX", "XX...XX", "XX...XX", "XX...XX", "XX...XX", ".XXXXX.",
    ),
    "-": (
        "...", "...", "...", "...", "...", "XXX",
        "XXX", "...", "...", "...", "...", "...",
    ),
}

_MASTER_MAP_GLYPHS: Dict[str, Tuple[str, ...]] = {
    **{key: _expand_master_map_glyph(value) for key, value in _ART_GLYPHS.items()},
    **_HAND_DRAWN_MASTER_MAP_GLYPHS,
}


# MIXED_EMOJI_COLUMNS is ~1.5k lines of emoji-grid string literals; it ships as
# package data (board_art/data/mixed_emoji_columns.txt) so this module stays under
# the authored-file line cap. Blocks are separated by a standalone sentinel line
# that cannot appear in the emoji data.
from importlib.resources import files as _resource_files

_MIXED_COLUMN_SEP = "@@YOKE-MIXED-COLUMN-SEP@@"
_MIXED_COLUMN_SEP_LINE = f"\n{_MIXED_COLUMN_SEP}\n"


def _parse_mixed_emoji_columns(text: str) -> Tuple[str, ...]:
    if _MIXED_COLUMN_SEP_LINE in text:
        text = text.replace(_MIXED_COLUMN_SEP_LINE, f"\n{_MIXED_COLUMN_SEP}")
    return tuple(text.split(_MIXED_COLUMN_SEP))


def _load_mixed_emoji_columns() -> Tuple[str, ...]:
    text = (
        _resource_files("yoke_contracts.project_contract.board_art.data")
        .joinpath("mixed_emoji_columns.txt")
        .read_text(encoding="utf-8")
    )
    return _parse_mixed_emoji_columns(text)


MIXED_EMOJI_COLUMNS: Tuple[str, ...] = _load_mixed_emoji_columns()
