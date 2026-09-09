"""Write-time contract for the glyph a project may give an execution lane.

The board renders a session row as ``<glyph> <label>`` inside fixed-width
columns, so a glyph that occupies a different number of terminal cells in
one emulator than another shears every row beneath it. The glyph
vocabulary Yoke ships is restricted to ``Emoji_Presentation=Yes``
characters — colour emoji that need no variation selector — and
:mod:`yoke_contracts.executor_labels` documents that convention for the
values held in source.

A scan over source cannot protect a glyph an operator types into project
settings, which is why this module exists: it is the same convention
applied at the moment a value is written, and every settings writer runs
it before storage.

Acceptance is deliberately narrow — exactly one code point whose Unicode
category is ``So`` and whose East Asian Width is ``W``. That pair is how
``Emoji_Presentation=Yes`` shows up in :mod:`unicodedata`, which carries
no emoji properties of its own: a text-default symbol such as U+26A0
WARNING SIGN is ``So`` but width ``N``, and only becomes emoji-shaped
with a U+FE0F this convention forbids. Everything a longer sequence could
express — a variation selector, a skin tone, a ZWJ family, a flag, a
keycap, a combining mark — is refused by name rather than silently
stripped, because storing a glyph that does not look like the one the
operator typed is its own defect.

Lives in ``yoke-contracts`` beside the board renderer and the executor
glyph map, so the engine can call it without either package importing the
other backwards.
"""

from __future__ import annotations

import unicodedata

from yoke_contracts.board.utils import display_width


SAFE_GLYPH_EXAMPLES: tuple[str, ...] = (
    "\U0001f40e",  # horse
    "\U0001f453",  # glasses
    "\U0001f6f8",  # flying saucer
    "\U0001f680",  # rocket
)
"""Glyphs an operator can copy straight into a lane that are known safe."""

BOARD_GLYPH_CELLS = 2
"""Terminal cells one board glyph must occupy for the columns to line up."""

_ZERO_WIDTH_JOINER = 0x200D
_COMBINING_KEYCAP = 0x20E3
_VARIATION_SELECTORS = range(0xFE00, 0xFE10)
_SKIN_TONE_MODIFIERS = range(0x1F3FB, 0x1F400)
_REGIONAL_INDICATORS = range(0x1F1E6, 0x1F200)

_RECOVERY = (
    "Use a single Emoji_Presentation glyph that needs no variation "
    "selector — for example "
    + " ".join(SAFE_GLYPH_EXAMPLES)
    + "."
)


class LaneGlyphError(ValueError):
    """Raised when a lane glyph would not render safely on the board."""


def _describe(code_point: int) -> str:
    """Name one code point the way a refusal should quote it."""
    char = chr(code_point)
    try:
        name = unicodedata.name(char)
    except ValueError:
        name = f"unnamed {unicodedata.category(char)} character"
    return f"U+{code_point:04X} {name}"


def _extra_code_point_reason(code_point: int) -> str:
    """Explain why the code point after the base disqualifies the glyph."""
    if code_point in _VARIATION_SELECTORS:
        return (
            f"a presentation selector ({_describe(code_point)}). A base that "
            "needs one is text-default, and terminals disagree about how wide "
            "it renders"
        )
    if code_point in _SKIN_TONE_MODIFIERS:
        return (
            f"a skin-tone modifier ({_describe(code_point)}), which collapses "
            "to a different width in some terminals"
        )
    if code_point == _ZERO_WIDTH_JOINER:
        return (
            "a zero-width joiner, so this is a multi-glyph sequence rather "
            "than one emoji"
        )
    if code_point == _COMBINING_KEYCAP:
        return "a combining enclosing keycap, so this is a keycap sequence"
    if code_point in _REGIONAL_INDICATORS:
        return (
            f"a regional indicator ({_describe(code_point)}), so this is a "
            "flag sequence rather than one emoji"
        )
    if unicodedata.category(chr(code_point)) in ("Mn", "Me", "Cf"):
        return f"a combining mark ({_describe(code_point)})"
    return f"a second character ({_describe(code_point)})"


def _is_text_default_symbol(code_point: int) -> bool:
    """True for a symbol whose emoji form requires a presentation selector."""
    char = chr(code_point)
    return (
        unicodedata.category(char) == "So"
        and unicodedata.east_asian_width(char) != "W"
        and code_point not in _REGIONAL_INDICATORS
    )


def _base_reason(code_point: int) -> str | None:
    """Explain why a single code point is not a board-safe emoji, if so."""
    char = chr(code_point)
    category = unicodedata.category(char)
    if category in ("Cc", "Cf", "Cs", "Co", "Cn"):
        return f"a control or non-character code point ({_describe(code_point)})"
    if code_point in _SKIN_TONE_MODIFIERS:
        return f"a bare skin-tone modifier ({_describe(code_point)})"
    if code_point in _REGIONAL_INDICATORS:
        return f"half of a flag sequence ({_describe(code_point)})"
    if category != "So":
        return (
            f"not a symbol character ({_describe(code_point)} is Unicode "
            f"category {category})"
        )
    if _is_text_default_symbol(code_point):
        return (
            f"a text-default symbol ({_describe(code_point)}). It renders as "
            "emoji only with a variation selector, which the board convention "
            "forbids"
        )
    return None


def lane_glyph_error(glyph: object) -> str | None:
    """Return why ``glyph`` is unsafe for the board, or ``None`` when it is safe.

    Exposed beside :func:`validate_lane_glyph` so a caller assembling a
    field-by-field report can collect reasons without catching one
    exception per field.
    """
    if not isinstance(glyph, str):
        return f"must be a string; got {type(glyph).__name__}"
    if not glyph:
        return "must not be empty"
    code_points = [ord(char) for char in glyph]
    base, *rest = code_points
    if rest and rest[0] in _VARIATION_SELECTORS and _is_text_default_symbol(base):
        # The operator supplied the selector on purpose, so saying only
        # "text-default symbol" would read as a contradiction. Name both
        # halves: the base needs the selector, and the selector is what the
        # board convention cannot carry.
        return (
            f"must be one terminal-safe emoji. {_describe(base)} renders as "
            f"emoji only with a presentation selector ({_describe(rest[0])}), "
            "and terminals disagree about how wide that pair renders, so the "
            "board convention allows neither"
        )
    reason = _base_reason(base)
    if reason is not None:
        return f"must be one terminal-safe emoji, but it is {reason}"
    if rest:
        return (
            "must be exactly one code point, but it also carries "
            + _extra_code_point_reason(rest[0])
        )
    width = display_width(glyph)
    if width != BOARD_GLYPH_CELLS:
        return (
            f"must occupy {BOARD_GLYPH_CELLS} terminal cells on the board, "
            f"but the board width helper measures {width}"
        )
    return None


def validate_lane_glyph(glyph: object, *, field: str = "glyph") -> str:
    """Return ``glyph`` unchanged when it is board-safe, else raise.

    ``field`` names the settings path the value came from so the refusal
    points at the key an operator has to edit.
    """
    reason = lane_glyph_error(glyph)
    if reason is None:
        return str(glyph)
    raise LaneGlyphError(f"{field} {reason}. {_RECOVERY}")


__all__ = [
    "BOARD_GLYPH_CELLS",
    "LaneGlyphError",
    "SAFE_GLYPH_EXAMPLES",
    "lane_glyph_error",
    "validate_lane_glyph",
]
