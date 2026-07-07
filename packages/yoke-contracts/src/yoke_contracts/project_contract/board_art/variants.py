"""Mixed ASCII+emoji board-art variant generation."""

from __future__ import annotations

from typing import List, Sequence, Tuple

from yoke_contracts.project_contract.board_art.ascii import (
    _fallback_ascii_art,
    _rank_figlet_fonts,
    _render_ascii_variant,
)
from yoke_contracts.project_contract.board_art._data import MIXED_EMOJI_COLUMNS
from yoke_contracts.project_contract.board_art.render_seed import (
    DEFAULT_VARIANT_MAX_WIDTH,
    MIXED_VARIANT_COUNT,
    MIXED_VARIANT_GAP,
    BoardArtVariant,
    _art_visual_width,
    _digest_for_parts,
    _fits_header_width,
    _pad_to_width,
    _resolve_seed,
    _trim_lines,
    choose_art_word,
)


def _rank_mixed_candidates(
    seed_text: str,
    *,
    salt: str,
    attempt: int,
) -> List[Tuple[str, int]]:
    candidates = [
        (font, column_index)
        for font in _rank_figlet_fonts(seed_text, salt=salt, attempt=attempt)
        for column_index in range(len(MIXED_EMOJI_COLUMNS))
    ]
    return sorted(
        candidates,
        key=lambda candidate: _digest_for_parts(
            salt, str(attempt), seed_text, candidate[0], str(candidate[1])
        ),
    )


def _rank_emoji_columns(seed_text: str, *, salt: str, attempt: int) -> List[int]:
    indexes = list(range(len(MIXED_EMOJI_COLUMNS)))
    return sorted(
        indexes,
        key=lambda index: _digest_for_parts(
            salt, str(attempt), seed_text, str(index)
        ),
    )


def _merge_blocks(
    left_lines: Sequence[str],
    right_lines: Sequence[str],
    *,
    gap: int = MIXED_VARIANT_GAP,
) -> List[str]:
    left = _trim_lines(tuple(left_lines))
    right = _trim_lines(tuple(right_lines))
    total = max(len(left), len(right))
    left_pad_top = (total - len(left)) // 2
    right_pad_top = (total - len(right)) // 2
    left_width = max((_art_visual_width(line) for line in left), default=0)
    gap_text = " " * gap
    result: List[str] = []

    for row_index in range(total):
        left_index = row_index - left_pad_top
        right_index = row_index - right_pad_top
        left_line = left[left_index] if 0 <= left_index < len(left) else ""
        right_line = right[right_index] if 0 <= right_index < len(right) else ""
        result.append(_pad_to_width(left_line, left_width) + gap_text + right_line)
    return result


def _compose_mixed_variant(ascii_art: str, emoji_column: str) -> str:
    return "\n".join(_merge_blocks(ascii_art.splitlines(), emoji_column.splitlines()))


def _mixed_detail(
    *,
    word: str,
    ascii_art: str,
    emoji_column: str,
    font: str | None,
    emoji_index: int | None,
) -> BoardArtVariant:
    return BoardArtVariant(
        kind="Mixed",
        text=_compose_mixed_variant(ascii_art, emoji_column),
        word=word,
        font=font,
        emoji_index=emoji_index,
        ascii_art=ascii_art,
        emoji_column=emoji_column,
    )


def _render_mixed_variant(font: str, word: str, emoji_column: str) -> str:
    return _compose_mixed_variant(_render_ascii_variant(font, word), emoji_column)


def _render_fallback_mixed_variant_detail(
    word: str,
    *,
    max_width: int,
    used_emoji_indexes: Sequence[int] = (),
) -> BoardArtVariant:
    ascii_art = _fallback_ascii_art(word)
    used = set(used_emoji_indexes)
    column_order = sorted(
        range(len(MIXED_EMOJI_COLUMNS)),
        key=lambda index: _art_visual_width(MIXED_EMOJI_COLUMNS[index]),
    )
    for pass_requires_new_column in (True, False):
        for column_index in column_order:
            if pass_requires_new_column and column_index in used:
                continue
            candidate = _mixed_detail(
                word=word,
                ascii_art=ascii_art,
                emoji_column=MIXED_EMOJI_COLUMNS[column_index],
                font=None,
                emoji_index=column_index,
            )
            if _fits_header_width(candidate.text, max_width):
                return candidate
    return BoardArtVariant(
        kind="Mixed", text=ascii_art, word=word, ascii_art=ascii_art,
    )


def _render_fallback_mixed_variant(
    word: str,
    *,
    max_width: int,
    used_emoji_indexes: Sequence[int] = (),
) -> Tuple[Tuple[str | None, int | None], str]:
    detail = _render_fallback_mixed_variant_detail(
        word, max_width=max_width, used_emoji_indexes=used_emoji_indexes,
    )
    return (detail.font, detail.emoji_index), detail.text


def _select_random_mixed_variant_detail(
    word: str,
    *,
    seed_text: str,
    attempt: int,
    max_width: int,
    used_fonts: Sequence[str] = (),
    used_pairs: Sequence[Tuple[str, int]] = (),
    used_emoji_indexes: Sequence[int] = (),
    keep_ascii_art: str | None = None,
    keep_font: str | None = None,
    keep_emoji_column: str | None = None,
    keep_emoji_index: int | None = None,
) -> BoardArtVariant:
    used_font_set = set(used_fonts)
    used_pair_set = set(used_pairs)
    used_column_set = set(used_emoji_indexes)

    if keep_ascii_art is not None:
        for pass_requires_new_column in (True, False):
            for column_index in _rank_emoji_columns(
                seed_text, salt="mixed-emoji", attempt=attempt,
            ):
                if pass_requires_new_column and column_index in used_column_set:
                    continue
                candidate = _mixed_detail(
                    word=word,
                    ascii_art=keep_ascii_art,
                    emoji_column=MIXED_EMOJI_COLUMNS[column_index],
                    font=keep_font,
                    emoji_index=column_index,
                )
                if _fits_header_width(candidate.text, max_width):
                    return candidate

    if keep_emoji_column is not None:
        for pass_requires_new_font in (True, False):
            for font in _rank_figlet_fonts(
                seed_text, salt="mixed-ascii", attempt=attempt,
            ):
                if pass_requires_new_font and font in used_font_set:
                    continue
                candidate = _mixed_detail(
                    word=word,
                    ascii_art=_render_ascii_variant(font, word),
                    emoji_column=keep_emoji_column,
                    font=font,
                    emoji_index=keep_emoji_index,
                )
                if _fits_header_width(candidate.text, max_width):
                    return candidate

    candidates = _rank_mixed_candidates(seed_text, salt="mixed", attempt=attempt)
    for pass_requires_new_column in (True, False):
        for font, column_index in candidates:
            if font in used_font_set or (font, column_index) in used_pair_set:
                continue
            if pass_requires_new_column and column_index in used_column_set:
                continue
            candidate = _mixed_detail(
                word=word,
                ascii_art=_render_ascii_variant(font, word),
                emoji_column=MIXED_EMOJI_COLUMNS[column_index],
                font=font,
                emoji_index=column_index,
            )
            if _fits_header_width(candidate.text, max_width):
                return candidate

    return _render_fallback_mixed_variant_detail(
        word, max_width=max_width, used_emoji_indexes=used_emoji_indexes,
    )


def _select_random_mixed_variant(
    word: str,
    *,
    seed_text: str,
    attempt: int,
    max_width: int,
    used_fonts: Sequence[str] = (),
    used_pairs: Sequence[Tuple[str, int]] = (),
    used_emoji_indexes: Sequence[int] = (),
) -> Tuple[Tuple[str | None, int | None], str]:
    detail = _select_random_mixed_variant_detail(
        word,
        seed_text=seed_text,
        attempt=attempt,
        max_width=max_width,
        used_fonts=used_fonts,
        used_pairs=used_pairs,
        used_emoji_indexes=used_emoji_indexes,
    )
    return (detail.font, detail.emoji_index), detail.text


def generate_random_mixed_variant_detail(
    display_name: str = "",
    *,
    slug: str | None = None,
    word: str | None = None,
    seed_text: str | None = None,
    attempt: int = 0,
    max_width: int = DEFAULT_VARIANT_MAX_WIDTH,
    used_fonts: Sequence[str] = (),
    used_pairs: Sequence[Tuple[str, int]] = (),
    used_emoji_indexes: Sequence[int] = (),
    keep_ascii_art: str | None = None,
    keep_font: str | None = None,
    keep_emoji_column: str | None = None,
    keep_emoji_index: int | None = None,
) -> BoardArtVariant:
    """Generate one width-bounded Mixed variant with rerollable parts.

    ``word`` overrides the auto-chosen project word (onboarding "customize
    text").
    """

    word = word if word is not None else choose_art_word(display_name, slug=slug)
    return _select_random_mixed_variant_detail(
        word,
        seed_text=_resolve_seed(seed_text),
        attempt=attempt,
        max_width=max_width,
        used_fonts=used_fonts,
        used_pairs=used_pairs,
        used_emoji_indexes=used_emoji_indexes,
        keep_ascii_art=keep_ascii_art,
        keep_font=keep_font,
        keep_emoji_column=keep_emoji_column,
        keep_emoji_index=keep_emoji_index,
    )


def generate_random_mixed_variant(
    display_name: str = "",
    *,
    slug: str | None = None,
    seed_text: str | None = None,
    attempt: int = 0,
    max_width: int = DEFAULT_VARIANT_MAX_WIDTH,
) -> str:
    """Generate one width-bounded Mixed variant for a project name."""

    return generate_random_mixed_variant_detail(
        display_name,
        slug=slug,
        seed_text=seed_text,
        attempt=attempt,
        max_width=max_width,
    ).text


def _select_mixed_variants(
    seed_text: str,
    word: str,
    *,
    used_fonts: Sequence[str] = (),
) -> Tuple[List[str], List[str]]:
    variants: List[str] = []
    selected_fonts: List[str] = []
    used_pairs: List[Tuple[str, int]] = []
    used_emoji_indexes: List[int] = []
    for attempt in range(MIXED_VARIANT_COUNT):
        selected, mixed_art = _select_random_mixed_variant(
            word,
            seed_text=seed_text,
            attempt=attempt,
            max_width=DEFAULT_VARIANT_MAX_WIDTH,
            used_fonts=[*used_fonts, *selected_fonts],
            used_pairs=used_pairs,
            used_emoji_indexes=used_emoji_indexes,
        )
        selected_font, selected_column = selected
        if selected_font is not None and selected_column is not None:
            selected_fonts.append(selected_font)
            used_pairs.append((selected_font, selected_column))
        if selected_column is not None:
            used_emoji_indexes.append(selected_column)
        variants.append(mixed_art)
    return variants, selected_fonts


def _render_mixed_variants(
    seed_text: str,
    word: str,
    *,
    used_fonts: Sequence[str] = (),
) -> List[str]:
    variants, _ = _select_mixed_variants(seed_text, word, used_fonts=used_fonts)
    return variants
