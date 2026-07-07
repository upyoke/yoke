"""ASCII pyfiglet board-art variant generation."""

from __future__ import annotations

from typing import List, Sequence, Tuple

import pyfiglet

from yoke_contracts.project_contract.board_art.render_seed import (
    ASCII_FIGLET_FONTS,
    DEFAULT_VARIANT_MAX_WIDTH,
    BoardArtVariant,
    _digest_for_parts,
    _fits_header_width,
    _resolve_seed,
    choose_art_word,
)

_FIGLET_RENDER_WIDTH = 1000


def _rank_figlet_fonts(seed_text: str, *, salt: str, attempt: int) -> List[str]:
    return sorted(
        ASCII_FIGLET_FONTS,
        key=lambda font: _digest_for_parts(salt, str(attempt), seed_text, font),
    )


def _protect_section_line(line: str) -> str:
    if line.startswith("## ") or line.startswith("---"):
        return " " + line
    return line


def _normalize_ascii_art(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    lines = [_protect_section_line(line) for line in lines]
    return "\n".join(lines)


def _fallback_ascii_art(word: str) -> str:
    label = f" {word} "
    border = "=" * max(12, len(label))
    return "\n".join((border, label.center(len(border)), border))


def _render_ascii_variant(font: str, word: str) -> str:
    rendered = pyfiglet.figlet_format(word, font=font, width=_FIGLET_RENDER_WIDTH)
    ascii_art = _normalize_ascii_art(rendered)
    if ascii_art:
        return ascii_art
    return _fallback_ascii_art(word)


def _select_random_ascii_variant(
    word: str,
    *,
    seed_text: str,
    attempt: int,
    max_width: int,
    used_fonts: Sequence[str] = (),
) -> Tuple[str | None, str]:
    used = set(used_fonts)
    for font in _rank_figlet_fonts(seed_text, salt="ascii", attempt=attempt):
        if font in used:
            continue
        ascii_art = _render_ascii_variant(font, word)
        if _fits_header_width(ascii_art, max_width):
            return font, ascii_art

    return None, _fallback_ascii_art(word)


def generate_random_ascii_variant_detail(
    display_name: str = "",
    *,
    slug: str | None = None,
    word: str | None = None,
    seed_text: str | None = None,
    attempt: int = 0,
    max_width: int = DEFAULT_VARIANT_MAX_WIDTH,
    used_fonts: Sequence[str] = (),
) -> BoardArtVariant:
    """Generate one width-bounded pyfiglet ASCII variant with metadata.

    ``word`` overrides the auto-chosen project word (used by onboarding's
    "customize text" — it bypasses the master-map length cap since pyfiglet art
    width-fits arbitrarily long text).
    """

    word = word if word is not None else choose_art_word(display_name, slug=slug)
    font, ascii_art = _select_random_ascii_variant(
        word,
        seed_text=_resolve_seed(seed_text),
        attempt=attempt,
        max_width=max_width,
        used_fonts=used_fonts,
    )
    return BoardArtVariant(
        kind="ASCII", text=ascii_art, word=word, font=font, ascii_art=ascii_art,
    )


def generate_random_ascii_variant(
    display_name: str = "",
    *,
    slug: str | None = None,
    seed_text: str | None = None,
    attempt: int = 0,
    max_width: int = DEFAULT_VARIANT_MAX_WIDTH,
) -> str:
    """Generate one width-bounded pyfiglet ASCII variant for a project name."""

    return generate_random_ascii_variant_detail(
        display_name,
        slug=slug,
        seed_text=seed_text,
        attempt=attempt,
        max_width=max_width,
    ).text


def _select_ascii_variants(
    seed_text: str,
    word: str,
    *,
    used_fonts: Sequence[str] = (),
) -> Tuple[List[str], List[str]]:
    variants: List[str] = []
    selected_fonts: List[str] = []
    for attempt in range(3):
        font, ascii_art = _select_random_ascii_variant(
            word,
            seed_text=seed_text,
            attempt=attempt,
            max_width=DEFAULT_VARIANT_MAX_WIDTH,
            used_fonts=[*used_fonts, *selected_fonts],
        )
        if font is not None:
            selected_fonts.append(font)
        variants.append(ascii_art)
    return variants, selected_fonts


def _render_ascii_variants(seed_text: str, word: str) -> List[str]:
    variants, _ = _select_ascii_variants(seed_text, word)
    return variants
