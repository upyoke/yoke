"""Shared constants and primitives for project board-art generation."""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from dataclasses import dataclass
from typing import List, Tuple

import pyfiglet

from yoke_contracts.project_contract.board_art.config import BLACK, WHITE
from yoke_contracts.project_contract.board_art._data import _MASTER_MAP_GLYPHS


MAX_ART_WORD_LEN = 8
FALLBACK_ART_WORD = "PROJECT"
ASCII_VARIANT_COUNT = 3
MIXED_VARIANT_COUNT = 3
MIXED_VARIANT_GAP = 2
# Emoji canvas budget for the image-to-art downsample pipeline (cols * rows =
# area cap). Independent of the product wordmark: it sizes the grid an arbitrary
# image is downsampled onto, not the YOKE header glyphs.
CURRENT_YOKE_MASTER_MAP_COLUMNS = 47
# Visual width of the rendered YOKE master-map wordmark. ``_master_map_lines``
# lays out one leading border column plus, per letter, the hand-tuned glyph
# cells and a trailing separator column, and every cell renders as a 2-wide
# emoji square. Derived from the actual glyph geometry so the variant-width
# invariant tracks the wordmark instead of the image canvas.
_YOKE_WORDMARK = "YOKE"
_MASTER_MAP_GLYPH_WIDTH = len(_MASTER_MAP_GLYPHS[_YOKE_WORDMARK[0]][0])
CURRENT_YOKE_MASTER_MAP_VISUAL_WIDTH = (
    1 + len(_YOKE_WORDMARK) * (_MASTER_MAP_GLYPH_WIDTH + 1)
) * 2
# Default visual-width ceiling for board-art variant generation — the interactive
# ``yoke board art variant create`` command, the library helpers, and
# onboarding seed art (``render_board_art``) all default to this bound. Kept
# separate from the master-map width so generated variants may run wider than the
# YOKE header; the generator still rejects anything above this bound.
DEFAULT_VARIANT_MAX_WIDTH = 140
# Fonts that render illegibly, too sparse, or too small for board art. The pool
# is allow-by-default (~570 pyfiglet fonts); grow this denylist as bad fonts are
# spotted. Names must match pyfiglet exactly — several carry trailing underscores
# (hills___, e__fist_, atc_____, b_m__200). Unknown names are harmless no-ops.
_DENIED_ASCII_FONTS = frozenset({
    "1943____", "1row", "3x5", "5x7", "5x8", "6x10",
    "6x9", "advenger", "alpha", "amc_3_liv1", "atc_____", "atc_gran",
    "b1ff", "b_m__200", "banner3", "battle_s", "battlesh", "baz__bil", "benjamin",
    "bigascii12", "bigascii9", "binary", "brite", "britebi", "britei", "bubble",
    "c1______", "caus_in_", "char1___", "char2___", "char4___", "charact3",
    "charset_", "chartr", "chartri", "circle", "clb6x10", "clb8x10", "clb8x8", "cli8x8",
    "clr4x6", "clr5x10", "clr5x6", "clr5x8", "clr6x10", "clr6x6",
    "clr6x8", "clr7x10", "clr7x8", "clr8x10", "clr8x8", "coil_cop",
    "contrast", "cour", "courb", "courbi", "couri", "cygnet",
    "danc4", "decimal", "deep_str", "devilish", "digital", "druid___",
    "dwhistled", "e__fist_", "eftichess", "eftipiti", "eftirobot", "eftiwall", "eftiwater",
    "fair_mea", "fairligh", "fantasy_", "finalass", "flyn_sh", "lexible_", "future_1",
    "future_2",
    "future_5", "future_7", "gauntlet", "ghost_bo", "goofy", "gradient",
    "grand_pr", "heavy_me", "helv", "helvb", "helvbi", "helvi", "hex",
    "hieroglyphs", "high_noo", "hills___", "home_pak", "hypa_bal", "icl-1900",
    "inc_raw_", "italic", "jerusalem", "joust___", "js_cursive", "katakana",
    "kik_star", "konto", "konto_slant", "lazy_jon", "lcd", "letterw3",
    "lil_devil", "mad_nurs", "magic_ma", "merlin2", "mike", "mirror", "mnemonic",
    "modern__", "morse", "morse2", "moscow", "mshebrew210", "notie_ca",
    "ntgreek", "octal", "odel_lak", "outrun__", "p_s_h_m_", "p_skateb",
    "pawn_ins", "phonix__", "platoon2",
    "pyramid", "r2-d2___", "rainbow_", "rally_s2", "rally_sp", "rampage_",
    "relief", "relief2", "ripper!_", "rockbox_", "rok_____", "rot13", "rotated",
    "runic", "runyc", "sans", "sansb", "sansbi", "sansi", "sbook",
    "sbookb", "sbookbi", "sbooki", "short", "skate_ro", "skateord", "skateroc", "slide",
    "smascii12", "smascii9", "smbraille", "smtengwar", "space_op", "star_strips",
    "stealth_", "stencil1", "stencil2", "subteran", "super_te", "tecrvs__",
    "tengwar", "term", "test1", "threepoint", "ticks", "ticksslant", "times",
    "t__of_ap", "timesofl", "top_duck", "trashman", "tsalagi", "tty", "ttyb", "twin_cob", "twopoint",
    "ugalympi", "unarmed_", "usaflag", "utopia", "utopiab", "utopiabi",
    "utopiai", "wideterm", "wow", "xbritebi", "xbritei", "xchartri",
    "xcour", "xcourb", "xcourbi", "xcouri", "xhelv", "xhelvb",
    "xhelvbi", "xhelvi", "xsans", "xsansb", "xsansbi", "xsansi",
    "xsbook", "xsbookb", "xsbookbi", "xsbooki", "xtimes", "xtty",
    "xttyb", "z-pilot_", "zig_zag_",
})
# pyfiglet ships padding-named decorative variants whose names carry a long run
# of underscores (pod_____, atc_____, roman___, …). Exclude them by rule so the
# denylist need not enumerate each one (and future ones auto-exclude).
_DECORATIVE_UNDERSCORE_RE = re.compile(r"_{3,}")
ASCII_FIGLET_FONTS: Tuple[str, ...] = tuple(
    font for font in sorted(pyfiglet.FigletFont.getFonts())
    if font not in _DENIED_ASCII_FONTS
    and not _DECORATIVE_UNDERSCORE_RE.search(font)
)


@dataclass(frozen=True)
class BoardArtVariant:
    """A generated board-art variant plus the parts needed to reroll it."""

    kind: str
    text: str
    word: str
    font: str | None = None
    emoji_index: int | None = None
    ascii_art: str | None = None
    emoji_column: str | None = None

_ART_HEADER = """\
# Board header art — read by the Yoke board renderer on every rebuild.
# Render tuning (bucket weights, frontier window) lives in .yoke/board.json;
# to pin a variant, set art_override there (e.g. frontier, rainbow_letters,
# ascii_1, mixed_1).
#
# Sections:
#   ## Master Map  -- emoji grid of {white} (fill target) and {black} (structural) cells;
#                     drives the frontier progress fill and rainbow modes.
#   ## Emoji       -- hand-drawn standalone emoji grids, rendered verbatim.
#   ## ASCII       -- raw monospace text art (no dimension constraints).
#   ## Mixed       -- text + emoji, pasted like ASCII art.
#
# A "# weight:N" line immediately above a section header weights that variant
# within its bucket; once any variant in a bucket carries a weight, unweighted
# variants in that bucket fall to 0. "# weight-disabled:N" is ignored (parked).
"""


def _tokens(value: str | None) -> List[str]:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.findall(r"[A-Za-z0-9]+", ascii_value.upper())


def choose_art_word(
    display_name: str,
    *,
    slug: str | None = None,
    max_len: int = MAX_ART_WORD_LEN,
) -> str:
    """Choose the word rendered in a new project's board art."""

    tokens = _tokens(display_name) or _tokens(slug)
    joined = "".join(tokens)
    if 1 <= len(joined) <= max_len:
        return joined

    acronym = "".join(token[0] for token in tokens if token)
    if len(tokens) > 1 and 2 <= len(acronym) <= max_len:
        return acronym

    if joined:
        return joined[:max_len]

    return FALLBACK_ART_WORD


# Header art (ASCII / Mixed / image-backed) renders through pyfiglet and a
# width-fit check, so it tolerates far longer text than the master map's fixed
# glyph grid — this cap only bounds runaway input; the generators still reject
# anything that does not fit ``max_width``.
MAX_HEADER_ART_WORD_LEN = 24

_VOWELS = frozenset("AEIOU")


def _drop_vowels_to_fit(word: str, max_len: int) -> str:
    """Shorten an over-long token: keep the first letter, drop interior vowels
    right-to-left until it fits, then hard-cut. Deterministic."""
    if len(word) <= max_len:
        return word
    first, rest = word[:1], list(word[1:])
    while len(rest) + len(first) > max_len:
        drop_at = next(
            (i for i in range(len(rest) - 1, -1, -1) if rest[i] in _VOWELS), None
        )
        if drop_at is None:
            break
        del rest[drop_at]
    return (first + "".join(rest))[:max_len]


def resolve_project_art_word(
    display_name: str = "",
    *,
    slug: str | None = None,
    short_code: str | None = None,
    max_len: int = MAX_ART_WORD_LEN,
) -> str:
    """Pick a board-art word from a project's name forms, most-recognizable first.

    Walks a ladder of candidate forms and returns the first that is
    ``1..max_len`` alphanumerics:

      1. the whole display name (tokens joined)
      2. the first word of the display name
      3. the display-name acronym (initials)
      4. the slug's first segment
      5. the short code (public item prefix, e.g. ``EXT``)

    If none fit, falls back to vowel-dropping truncation of the best human
    candidate, then to :data:`FALLBACK_ART_WORD`. Every form is normalized to
    uppercase alphanumerics so the result is a valid master-map glyph word.
    """
    display_tokens = _tokens(display_name)
    slug_tokens = _tokens(slug)

    candidates: List[str] = ["".join(display_tokens)]
    if display_tokens:
        candidates.append(display_tokens[0])
    if len(display_tokens) > 1:
        candidates.append("".join(token[0] for token in display_tokens))
    if slug_tokens:
        candidates.append(slug_tokens[0])
    code = "".join(_tokens(short_code))
    if code:
        candidates.append(code)

    for candidate in candidates:
        if 1 <= len(candidate) <= max_len:
            return candidate

    best = next((candidate for candidate in candidates if candidate), "")
    if best:
        truncated = _drop_vowels_to_fit(best, max_len)
        if truncated:
            return truncated
    return FALLBACK_ART_WORD[:max_len]


def normalize_master_map_word(value: str, *, max_len: int = MAX_ART_WORD_LEN) -> str:
    """Coerce free text to a master-map word: uppercase glyph-set alphanumerics,
    capped to ``max_len``. Returns ``""`` when nothing usable remains."""
    return "".join(_tokens(value))[:max_len]


def normalize_header_art_word(
    value: str, *, max_len: int = MAX_HEADER_ART_WORD_LEN
) -> str:
    """Coerce free text to a header-art word: letters, numbers, and single
    spaces, uppercased, capped to ``max_len``. Header art renders through
    pyfiglet so spaces and longer words are fine; the empty string maps to
    ``""`` so callers can fall back to the default word."""
    upper = "".join(
        ch if (ch.isalnum() or ch == " ") else " " for ch in value.upper()
    )
    return " ".join(upper.split())[:max_len]


def _master_map_lines(word: str) -> List[str]:
    rows: List[str] = []
    for row_index in range(len(next(iter(_MASTER_MAP_GLYPHS.values())))):
        cells = ["."]
        for letter in word:
            cells.append(_MASTER_MAP_GLYPHS[letter][row_index])
            cells.append(".")
        rows.append("".join(cells))
    border = "." * len(rows[0])
    rows.insert(0, border)
    rows.append(border)
    return [row.replace("X", WHITE).replace(".", BLACK) for row in rows]


def _digest_for(seed_text: str) -> bytes:
    return hashlib.sha256(seed_text.encode("utf-8")).digest()


def _digest_for_parts(*parts: str) -> bytes:
    return _digest_for("\0".join(parts))


def _resolve_seed(seed_text: str | None) -> str:
    return seed_text if seed_text is not None else secrets.token_hex(16)


def _is_wide_char(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x1F300 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0x2B1B <= cp <= 0x2B1C
        or 0x2B50 <= cp <= 0x2B55
        or 0x1100 <= cp <= 0x115F
        or 0x2E80 <= cp <= 0x303E
        or 0x3040 <= cp <= 0xA4CF
        or 0xAC00 <= cp <= 0xD7AF
        or 0xF900 <= cp <= 0xFAFF
        or 0xFF00 <= cp <= 0xFF60
        or 0xFFE0 <= cp <= 0xFFE6
    )


def _visual_width(text: str) -> int:
    return sum(2 if _is_wide_char(ch) else 1 for ch in text)


def _art_visual_width(text: str) -> int:
    return max((_visual_width(line) for line in text.splitlines()), default=0)


def _fits_header_width(text: str, max_width: int) -> bool:
    return _art_visual_width(text) <= max_width


def _pad_to_width(text: str, width: int) -> str:
    return text + " " * max(0, width - _visual_width(text))


def _trim_lines(lines: list[str] | tuple[str, ...]) -> List[str]:
    start = 0
    end = len(lines) - 1
    while start <= end and not lines[start].strip():
        start += 1
    while end >= start and not lines[end].strip():
        end -= 1
    return list(lines[start:end + 1])
