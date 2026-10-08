"""The level glyph a project may store must render at one board width.

The board convention lives in source as ``Emoji_Presentation=Yes`` glyphs
with no variation selector and no skin tone, and a source scan protects the
values Yoke ships. A level glyph is typed by an operator and stored, so the
same convention has to hold at the write boundary — these cases are the
sequence families a person can plausibly paste that a scan would never see.
"""

from __future__ import annotations

import pytest

from yoke_contracts.board.utils import display_width
from yoke_contracts.executor_labels import EXECUTOR_EMOJI
from yoke_contracts.level_glyph import (
    BOARD_GLYPH_CELLS,
    LevelGlyphError,
    SAFE_GLYPH_EXAMPLES,
    level_glyph_error,
    validate_level_glyph,
)
from yoke_contracts.session_level import DEFAULT_LEVEL_METADATA


class TestAcceptedGlyphs:
    @pytest.mark.parametrize("glyph", SAFE_GLYPH_EXAMPLES)
    def test_the_offered_examples_are_accepted(self, glyph):
        assert validate_level_glyph(glyph) == glyph

    @pytest.mark.parametrize("glyph", sorted(EXECUTOR_EMOJI.values()))
    def test_every_shipped_board_glyph_is_accepted(self, glyph):
        # The level vocabulary and the executor vocabulary render into the
        # same board columns, so one convention has to cover both.
        assert level_glyph_error(glyph) is None

    @pytest.mark.parametrize(
        "level",
        sorted(DEFAULT_LEVEL_METADATA),
    )
    def test_the_shipped_level_defaults_are_accepted(self, level):
        assert level_glyph_error(DEFAULT_LEVEL_METADATA[level]["glyph"]) is None

    @pytest.mark.parametrize("glyph", SAFE_GLYPH_EXAMPLES)
    def test_accepted_glyphs_measure_one_board_column(self, glyph):
        # Measured with the renderer's own helper rather than a length: the
        # column alignment this contract protects is what that helper reports.
        assert display_width(glyph) == BOARD_GLYPH_CELLS


class TestRefusedSequences:
    @pytest.mark.parametrize(
        "glyph,expected",
        [
            ("\U0001f3d7️", "presentation selector"),
            ("⚠️", "presentation selector"),
            ("\U0001f44d\U0001f3fb", "skin-tone modifier"),
            ("\U0001f468‍\U0001f469‍\U0001f466", "zero-width joiner"),
            ("\U0001f1fa\U0001f1f8", "flag sequence"),
            ("1️⃣", "not a symbol character"),
            ("é", "not a symbol character"),
            ("\U0001f3fb", "bare skin-tone modifier"),
            ("\x07", "control or non-character"),
            ("\U0001f40e\U0001f453", "second character"),
        ],
    )
    def test_named_reason_for_each_family(self, glyph, expected):
        reason = level_glyph_error(glyph)
        assert reason is not None
        assert expected in reason

    @pytest.mark.parametrize("glyph", ["❤", "\U0001f3d7", "⚠"])
    def test_text_default_symbols_are_refused_without_their_selector(self, glyph):
        # These are the glyphs whose emoji form REQUIRES the selector the
        # convention forbids, so accepting the bare base would store one
        # thing and render another.
        assert "text-default symbol" in (level_glyph_error(glyph) or "")

    @pytest.mark.parametrize("glyph", ["", None, 7, []])
    def test_non_glyphs_are_refused(self, glyph):
        assert level_glyph_error(glyph) is not None


class TestRefusalWording:
    def test_the_refusal_names_the_field_and_offers_safe_glyphs(self):
        with pytest.raises(LevelGlyphError) as caught:
            validate_level_glyph("⚠️", field="level_metadata.X.glyph")
        message = str(caught.value)
        assert message.startswith("level_metadata.X.glyph ")
        for example in SAFE_GLYPH_EXAMPLES:
            assert example in message

    def test_an_unsafe_glyph_is_never_silently_repaired(self):
        # Stripping the selector would store a glyph that looks different
        # from the one the operator typed, which is its own defect.
        with pytest.raises(LevelGlyphError):
            validate_level_glyph("\U0001f3d7️")
