"""Shared utilities for board rendering."""

from __future__ import annotations

import unicodedata


# Unicode 15.1 Emoji_Modifier_Base set — the emoji that legitimately absorb
# a following skin-tone modifier (U+1F3FB..U+1F3FF) into a single glyph.
# A skin tone after any other emoji (🟥, 🟩, ⬜, etc.) is a standalone emoji
# in its own right and must count as its own width-2 glyph.
_EMOJI_MODIFIER_BASE = frozenset({
    0x261D, 0x26F9,
    *range(0x270A, 0x270E),         # ✊..✍
    0x1F385,
    *range(0x1F3C2, 0x1F3C5),       # 🏂..🏄
    0x1F3C7,
    *range(0x1F3CA, 0x1F3CD),       # 🏊..🏌
    *range(0x1F442, 0x1F444),       # 👂..👃
    *range(0x1F446, 0x1F451),       # 👆..👐
    *range(0x1F466, 0x1F479),       # 👦..👸
    0x1F47C,
    *range(0x1F481, 0x1F484),       # 💁..💃
    *range(0x1F485, 0x1F488),       # 💅..💇
    0x1F48F, 0x1F491, 0x1F4AA,
    *range(0x1F574, 0x1F576),       # 🕴..🕵
    0x1F57A, 0x1F590,
    0x1F595, 0x1F596,
    *range(0x1F645, 0x1F648),       # 🙅..🙇
    *range(0x1F64B, 0x1F650),       # 🙋..🙏
    0x1F6A3,
    *range(0x1F6B4, 0x1F6B7),       # 🚴..🚶
    0x1F6C0, 0x1F6CC,
    0x1F90C, 0x1F90F,
    *range(0x1F918, 0x1F920),       # 🤘..🤟
    0x1F926,
    *range(0x1F930, 0x1F93A),       # 🤰..🤹
    *range(0x1F93C, 0x1F93F),       # 🤼..🤾
    0x1F977,
    *range(0x1F9B5, 0x1F9B7),       # 🦵..🦶
    *range(0x1F9B8, 0x1F9BA),       # 🦸..🦹
    0x1F9BB,
    *range(0x1F9CD, 0x1F9D0),       # 🧍..🧏
    *range(0x1F9D1, 0x1F9DE),       # 🧑..🧝
    *range(0x1FAC3, 0x1FAC6),       # 🫃..🫅
    *range(0x1FAF0, 0x1FAF9),       # 🫰..🫸
})


def display_width(s: str) -> int:
    """Estimate monospace display width, accounting for emoji as 2-cell glyphs.

    Emoji sequences (ZWJ, skin tone, keycap, presentation) render as a single
    2-cell glyph in modern terminals.  We consume entire sequences and count
    each as width 2.
    """
    _ZW_CATS = {"Mn", "Me", "Cf"}

    w = 0
    i = 0
    chars = list(s)
    n = len(chars)
    while i < n:
        c = chars[i]
        cp = ord(c)

        # --- Zero-width: combining marks, ZWJ, variation selectors ---
        if unicodedata.category(c) in _ZW_CATS:
            i += 1
            continue

        # --- Keycap sequence: digit/# + VS16? + U+20E3 ---
        if cp in (*range(0x30, 0x3A), 0x23, 0x2A):
            j = i + 1
            if j < n and ord(chars[j]) == 0xFE0F:
                j += 1
            if j < n and ord(chars[j]) == 0x20E3:
                w += 2
                i = j + 1
                continue

        # --- Emoji detection ---
        is_emoji = False
        if cp > 0xFFFF:
            is_emoji = True
        elif unicodedata.category(c) == "So":
            # Symbol, Other — but only wide ones are emoji (⬜⬛✨ etc.)
            # Narrow "So" chars (box drawing ║, misc symbols) stay width 1.
            ea = unicodedata.east_asian_width(c)
            if ea in ("W", "F"):
                is_emoji = True
        # Explicit BMP emoji that may not have ea_width "W"
        #
        # Geometric Shapes block chars (U+25AA..U+25FE) are intentionally
        # excluded here. They have Emoji_Presentation=No (text-default) and
        # render narrow in monospace terminals unless followed by VS16.
        # Including them broke mixed-art alignment when ASCII YOKE glyphs
        # used ▪ (U+25AA) as a block-drawing element. U+25FD and U+25FE
        # remain width 2 via the East Asian Width=W fallback below.
        if not is_emoji and cp in (
            0x2702, 0x2708, 0x2709, 0x270A, 0x270B, 0x270C, 0x270D,
            0x270F, 0x2712, 0x2714, 0x2716, 0x271D, 0x2721, 0x2733,
            0x2734, 0x2744, 0x2747, 0x274C, 0x274E, 0x2753, 0x2754,
            0x2755, 0x2757, 0x2763, 0x2764,
            # Regional indicators, flags, etc.
            0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139,
            0x2194, 0x2195, 0x2196, 0x2197, 0x2198, 0x2199,
            0x21A9, 0x21AA, 0x231A, 0x231B, 0x2328, 0x23CF,
            0x23E9, 0x23EA, 0x23EB, 0x23EC, 0x23ED, 0x23EE,
            0x23EF, 0x23F0, 0x23F1, 0x23F2, 0x23F3, 0x23F8,
            0x23F9, 0x23FA, 0x2600, 0x2601,
            0x2602, 0x2603, 0x2604, 0x260E, 0x2611, 0x2614,
            0x2615, 0x2618, 0x261D, 0x2620, 0x2622, 0x2623,
            0x2626, 0x262A, 0x262E, 0x262F, 0x2638, 0x2639,
            0x263A, 0x2640, 0x2642, 0x2648, 0x2649, 0x264A,
            0x264B, 0x264C, 0x264D, 0x264E, 0x264F, 0x2650,
            0x2651, 0x2652, 0x2653, 0x265F, 0x2660, 0x2663,
            0x2665, 0x2666, 0x2668, 0x267B, 0x267E, 0x267F,
            0x2692, 0x2693, 0x2694, 0x2695, 0x2696, 0x2697,
            0x2699, 0x269B, 0x269C, 0x26A0, 0x26A1, 0x26AA,
            0x26AB, 0x26B0, 0x26B1, 0x26BD, 0x26BE, 0x26C4,
            0x26C5, 0x26C8, 0x26CE, 0x26CF, 0x26D1, 0x26D3,
            0x26D4, 0x26E9, 0x26EA, 0x26F0, 0x26F1, 0x26F2,
            0x26F3, 0x26F4, 0x26F5, 0x26F7, 0x26F8, 0x26F9,
            0x26FA, 0x26FD,
        ):
            is_emoji = True

        if is_emoji:
            w += 2
            i += 1
            # Track the last base emoji in the sequence. Skin-tone modifiers
            # may only attach to emoji in Emoji_Modifier_Base; otherwise the
            # skin tone is a standalone glyph and must be left for the next
            # outer iteration to count as its own width-2 emoji.
            last_base = cp
            # Consume trailing modifiers: VS16, skin tones, ZWJ sequences
            while i < n:
                nc = ord(chars[i])
                if nc == 0xFE0F or nc == 0xFE0E:
                    i += 1  # variation selector
                elif 0x1F3FB <= nc <= 0x1F3FF:
                    if last_base in _EMOJI_MODIFIER_BASE:
                        i += 1  # skin tone modifier (legitimate)
                    else:
                        break    # skin tone is standalone — stop consuming
                elif nc == 0x200D and i + 1 < n:
                    i += 1  # ZWJ
                    # consume the joined emoji
                    if i < n:
                        last_base = ord(chars[i])
                        i += 1
                elif unicodedata.category(chars[i]) in _ZW_CATS:
                    i += 1
                elif nc == 0x20E3:
                    i += 1  # combining enclosing keycap
                else:
                    break
            continue

        # --- East Asian wide/fullwidth ---
        ea = unicodedata.east_asian_width(c)
        if ea in ("W", "F"):
            w += 2
        else:
            w += 1
        i += 1
    return w
