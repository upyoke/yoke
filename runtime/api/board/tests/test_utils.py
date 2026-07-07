"""Tests for yoke_contracts.board.utils — display_width emoji measurement.

Covers:
- ASCII characters (width 1 each)
- BMP emoji (width 2 each)
- Supplementary-plane emoji (width 2 each)
- Skin-toned emoji sequences (width 2 total)
- ZWJ sequences (width 2 total)
- Variation selector handling (U+FE0F stripped, U+2764 + FE0F = width 2)
- Mixed ASCII + emoji lines
- East Asian wide characters
"""

from __future__ import annotations

import pytest

from yoke_contracts.board.utils import display_width


class TestDisplayWidthAscii:
    """Plain ASCII text."""

    def test_empty(self):
        assert display_width("") == 0

    def test_simple(self):
        assert display_width("hello") == 5

    def test_spaces(self):
        assert display_width("   ") == 3

    def test_hash_art(self):
        assert display_width("#####   #    #") == 14


class TestDisplayWidthEmoji:
    """Emoji width measurement."""

    def test_single_supplementary_emoji(self):
        # 👉 = U+1F449, supplementary plane
        assert display_width("\U0001f449") == 2

    def test_skin_tone_emoji(self):
        # 👉🏿 = U+1F449 + U+1F3FF (dark skin tone)
        assert display_width("\U0001f449\U0001f3ff") == 2

    def test_heart_with_vs16(self):
        # ❤️ = U+2764 + U+FE0F
        assert display_width("\u2764\ufe0f") == 2

    def test_heart_without_vs16(self):
        # ❤ = U+2764 alone (still emoji in So category)
        assert display_width("\u2764") == 2

    def test_two_hearts_vs16(self):
        # ❤️❤️ should be width 4
        assert display_width("\u2764\ufe0f\u2764\ufe0f") == 4

    def test_two_skin_toned_pointing(self):
        # 👉🏿👉🏾 = 2 emoji, each width 2 = total 4
        assert display_width("\U0001f449\U0001f3ff\U0001f449\U0001f3fe") == 4

    def test_white_square(self):
        # ⬜ = U+2B1C
        assert display_width("\u2b1c") == 2

    def test_black_square(self):
        # ⬛ = U+2B1B
        assert display_width("\u2b1b") == 2

    def test_color_square(self):
        # 🟨 = U+1F7E8
        assert display_width("\U0001f7e8") == 2

    def test_moon_phases(self):
        # 🌕🌘🌑🌒 = 4 emoji, each width 2 = 8
        assert display_width("\U0001f315\U0001f318\U0001f311\U0001f312") == 8


class TestDisplayWidthMixed:
    """Mixed ASCII + emoji lines (the board art use case)."""

    def test_art_with_pointing_emojis(self):
        # Simulates a line like: "##### " + 11 skin-toned pointing emoji
        ascii_part = "#####   "
        # 👉🏿👉🏾👉🏽👉🏼👇🏻👇🏻👇🏻👈🏼👈🏽👈🏾👈🏿
        emoji_part = (
            "\U0001f449\U0001f3ff"  # 👉🏿
            "\U0001f449\U0001f3fe"  # 👉🏾
            "\U0001f449\U0001f3fd"  # 👉🏽
            "\U0001f449\U0001f3fc"  # 👉🏼
            "\U0001f447\U0001f3fb"  # 👇🏻
            "\U0001f447\U0001f3fb"  # 👇🏻
            "\U0001f447\U0001f3fb"  # 👇🏻
            "\U0001f448\U0001f3fc"  # 👈🏼
            "\U0001f448\U0001f3fd"  # 👈🏽
            "\U0001f448\U0001f3fe"  # 👈🏾
            "\U0001f448\U0001f3ff"  # 👈🏿
        )
        w = display_width(ascii_part + emoji_part)
        assert w == 8 + 22  # 8 ASCII chars + 11 emoji * 2

    def test_art_with_hearts(self):
        # Simulates the hearts line: "##### " + 4 pointing + 2 hearts + 4 pointing
        ascii_part = "#####   "
        emoji_part = (
            "\U0001f449\U0001f3ff"  # 👉🏿
            "\U0001f449\U0001f3fe"  # 👉🏾
            "\U0001f449\U0001f3fd"  # 👉🏽
            "\U0001f449\U0001f3fc"  # 👉🏼
            "\U0001f449\U0001f3fb"  # 👉🏻
            "\u2764\ufe0f"          # ❤️
            "\u2764\ufe0f"          # ❤️
            "\U0001f448\U0001f3fc"  # 👈🏼
            "\U0001f448\U0001f3fd"  # 👈🏽
            "\U0001f448\U0001f3fe"  # 👈🏾
            "\U0001f448\U0001f3ff"  # 👈🏿
        )
        w = display_width(ascii_part + emoji_part)
        assert w == 8 + 22  # 8 ASCII chars + 11 emoji * 2

    def test_hearts_and_pointing_same_width(self):
        """The core bug: hearts row must equal pointing row width."""
        # Row with 11 pointing emoji (various skin tones)
        pointing = (
            "\U0001f449\U0001f3ff\U0001f449\U0001f3fe\U0001f449\U0001f3fd"
            "\U0001f449\U0001f3fc\U0001f447\U0001f3fb\U0001f447\U0001f3fb"
            "\U0001f447\U0001f3fb\U0001f448\U0001f3fc\U0001f448\U0001f3fd"
            "\U0001f448\U0001f3fe\U0001f448\U0001f3ff"
        )
        # Row with 4 pointing + 2 hearts + 5 pointing (same 11 emoji)
        hearts = (
            "\U0001f449\U0001f3ff\U0001f449\U0001f3fe\U0001f449\U0001f3fd"
            "\U0001f449\U0001f3fc\U0001f449\U0001f3fb"
            "\u2764\ufe0f\u2764\ufe0f"
            "\U0001f448\U0001f3fc\U0001f448\U0001f3fd"
            "\U0001f448\U0001f3fe\U0001f448\U0001f3ff"
        )
        assert display_width(pointing) == display_width(hearts)

    def test_mixed_art_with_box_drawing(self):
        """Stats box lines with box drawing + emoji."""
        line = " \u2551 \U0001f525 Active    14  \u2b1c\u2b1c\u2b1c\u2b1b\u2b1b\u2b1b\u2b1b\u2b1b\u2b1b\u2b1b"
        w = display_width(line)
        # " " = 1, ║ = 1 (box drawing, not emoji), " " = 1, 🔥 = 2, " Active    14  " = 15, 10 squares * 2 = 20
        assert w == 1 + 1 + 1 + 2 + 15 + 20

    def test_geometric_shape_text_default_narrow(self):
        """Geometric Shapes block text-default chars render narrow in terminals.

        ▪ ▫ ▶ ◀ ◻ ◼ have Emoji_Presentation=No and must be width 1 so that
        ASCII YOKE glyphs in mixed-art variants align with the stats box.
        """
        assert display_width("\u25aa") == 1  # ▪
        assert display_width("\u25ab") == 1  # ▫
        assert display_width("\u25b6") == 1  # ▶
        assert display_width("\u25c0") == 1  # ◀
        assert display_width("\u25fb") == 1  # ◻
        assert display_width("\u25fc") == 1  # ◼

    def test_geometric_shape_emoji_default_wide(self):
        """Emoji_Presentation=Yes shapes (EA=W) stay width 2."""
        assert display_width("\u25fd") == 2  # ◽
        assert display_width("\u25fe") == 2  # ◾

    def test_standalone_skin_tone_after_non_modifier_base(self):
        """Skin tones after squares/shapes are standalone width-2 emoji.

        Skin-tone modifiers (🏻-🏿) only combine with Emoji_Modifier_Base
        emoji (people, hands, etc.). After a 🟥 or 🟩 or ⬜, each 🏻 is its
        own emoji glyph and must count as width 2.
        """
        red_skin = "\U0001f7e5\U0001f3fb"
        assert display_width(red_skin) == 4
        green_two_skins = "\U0001f7e9" + "\U0001f3fb" * 2
        assert display_width(green_two_skins) == 6
        green_six_skins = "\U0001f7e9" + "\U0001f3fb" * 6
        assert display_width(green_six_skins) == 14

    def test_legit_skin_tone_modifier_still_combines(self):
        """Skin tones after modifier-base emoji still combine into one glyph."""
        assert display_width("\U0001f449\U0001f3ff") == 2  # 👉🏿
        assert display_width("\u270b\U0001f3fd") == 2      # ✋🏽
        assert display_width("\U0001f4aa\U0001f3fc") == 2  # 💪🏼

    def test_zwj_with_skin_tone_then_non_base(self):
        """👨🏻‍💻: 👨 is modifier base; 💻 after ZWJ is not, so a trailing
        skin tone on 💻 (if present) would not combine."""
        assert display_width(
            "\U0001f468\U0001f3fb\u200d\U0001f4bb"
        ) == 2

    def test_ascii_yoke_mixed_rows_equal_width(self):
        """Regression: mushroom mixed variant rows with varying ▪ counts.

        Before the fix, ▪ was counted as width 2, so rows with different
        ▪ counts produced drifting widths, breaking stats-box alignment.
        """
        rows = [
            ".▄▄ · ▄• ▄▌ ▐ ▄ ·▄▄▄▄   ▄▄▄·  ▄· ▄▌",   # 0 ▪
            "▐█ ▀. █▪██▌•█▌▐███▪ ██ ▐█ ▀█ ▐█▪██▌",   # 3 ▪
            "▄▀▀▀█▄█▌▐█▌▐█▐▐▌▐█· ▐█▌▄█▀▀█ ▐█▌▐█▪",   # 1 ▪
            "▐█▄▪▐█▐█▄█▌██▐█▌██. ██ ▐█ ▪▐▌ ▐█▀·.",   # 2 ▪
        ]
        widths = {display_width(r) for r in rows}
        assert len(widths) == 1, f"rows have drifting widths: {widths}"


class TestDisplayWidthEastAsian:
    """East Asian wide/fullwidth characters."""

    def test_cjk(self):
        assert display_width("\u4e2d\u6587") == 4  # 中文

    def test_fullwidth_latin(self):
        assert display_width("\uff21") == 2  # Ａ (fullwidth A)
