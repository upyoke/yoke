"""Tests for generalized letter-geometry resolution.

Covers the ``# letters:`` directive parse, auto-derivation from a master map,
the resolution priority, and that letter-aware rainbow fills honor derived
spans for a non-YOKE word.
"""

from __future__ import annotations

import random

from yoke_contracts.project_contract.board_art.config import (
    BLACK,
    LETTER_BOUNDS,
    WHITE,
    _parse_letter_bounds_directive,
    derive_letter_bounds,
    resolve_letter_bounds,
)
from yoke_contracts.board.art_rainbow import _fill_rainbow_letters


def _row(spec: str) -> str:
    """Build a grid row from a ``#``/``.`` sketch (# = WHITE, . = BLACK)."""
    return "".join(WHITE if c == "#" else BLACK for c in spec)


# Two letters, each 2 cols wide, parted by one all-black column.
TWO_LETTERS = [
    _row(".##.##."),
    _row(".##.##."),
    _row(".......",),
]

# Two letters kerned together (no separating all-black column).
KERNED = [
    _row(".####."),
    _row("#....#"),
    _row("......"),
]


class TestParseDirective:
    def test_basic(self):
        line = "# letters: 1-7,9-15,17-23"
        assert _parse_letter_bounds_directive(line) == [(1, 7), (9, 15), (17, 23)]

    def test_whitespace_and_blanks(self):
        line = "# letters:  2-10 , 13-21 ,"
        assert _parse_letter_bounds_directive(line) == [(2, 10), (13, 21)]

    def test_malformed_entries_skipped(self):
        line = "# letters: 1-7,oops,9-x,11-15"
        assert _parse_letter_bounds_directive(line) == [(1, 7), (11, 15)]

    def test_empty(self):
        assert _parse_letter_bounds_directive("# letters:") == []


class TestDerive:
    def test_separated_letters(self):
        assert derive_letter_bounds(TWO_LETTERS) == [(1, 2), (4, 5)]

    def test_kerned_letters_merge(self):
        # No all-black column between the two glyphs -> one merged span.
        assert derive_letter_bounds(KERNED) == [(0, 5)]

    def test_empty_map(self):
        assert derive_letter_bounds([]) == []
        assert derive_letter_bounds(["", "  "]) == []


class TestResolve:
    def test_declared_wins(self):
        declared = [(0, 3), (5, 8)]
        assert resolve_letter_bounds(declared, TWO_LETTERS) == declared

    def test_auto_derive_when_undeclared(self):
        assert resolve_letter_bounds([], TWO_LETTERS) == [(1, 2), (4, 5)]

    def test_fallback_to_builtin(self):
        # No declaration and a map that yields < 2 letters -> YOKE default.
        assert resolve_letter_bounds([], KERNED) == list(LETTER_BOUNDS)
        assert resolve_letter_bounds([], []) == list(LETTER_BOUNDS)


class TestLetterFillHonorsBounds:
    def test_each_band_single_color(self):
        # A 4-letter map; every WHITE cell in a band must share one color.
        bounds = [(1, 2), (4, 5), (7, 8), (10, 11)]
        grid = [
            _row(".##.##.##.##."),
            _row(".##.##.##.##."),
        ]
        filled = _fill_rainbow_letters(grid, random.Random(7), bounds)
        # Collect the color landing on each band, per row, and assert uniform.
        for row in filled:
            cells = list(row)
            for lo, hi in bounds:
                band = {cells[c] for c in range(lo, hi + 1) if cells[c] != BLACK}
                assert len(band) == 1, (lo, hi, band)
