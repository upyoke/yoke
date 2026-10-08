"""Every glyph Yoke stores must render at one board width.

The board convention lives in source as ``Emoji_Presentation=Yes`` glyphs
with no variation selector and no skin tone, and a source scan protects the
values Yoke ships. Project emoji, workflow stage glyphs, and level glyphs
are supplied at write time and stored, so the same convention has to hold at
the write boundary — these cases are the sequence families a person can
plausibly paste that a scan would never see.
"""

from __future__ import annotations

import pytest

from yoke_contracts.board.utils import display_width
from yoke_contracts.executor_labels import EXECUTOR_EMOJI
from yoke_contracts.glyph_contract import (
    BOARD_GLYPH_CELLS,
    GlyphContractError,
    SAFE_GLYPH_EXAMPLES,
    glyph_contract_error,
    validate_glyph,
)
from yoke_contracts.lifecycle_status import LEGACY_STATUS_GLYPHS
from yoke_contracts.session_level import DEFAULT_LEVEL_METADATA


class TestAcceptedGlyphs:
    @pytest.mark.parametrize("glyph", SAFE_GLYPH_EXAMPLES)
    def test_the_offered_examples_are_accepted(self, glyph):
        assert validate_glyph(glyph) == glyph

    @pytest.mark.parametrize("glyph", sorted(EXECUTOR_EMOJI.values()))
    def test_every_shipped_board_glyph_is_accepted(self, glyph):
        # Every shipped vocabulary renders into the same board columns, so
        # one convention has to cover them all.
        assert glyph_contract_error(glyph) is None

    @pytest.mark.parametrize(
        "level",
        sorted(DEFAULT_LEVEL_METADATA),
    )
    def test_the_shipped_level_defaults_are_accepted(self, level):
        assert glyph_contract_error(DEFAULT_LEVEL_METADATA[level]["glyph"]) is None

    @pytest.mark.parametrize("stage", sorted(LEGACY_STATUS_GLYPHS))
    def test_the_shipped_stage_glyphs_are_accepted(self, stage):
        assert glyph_contract_error(LEGACY_STATUS_GLYPHS[stage]) is None

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
        reason = glyph_contract_error(glyph)
        assert reason is not None
        assert expected in reason

    @pytest.mark.parametrize("glyph", ["❤", "\U0001f3d7", "⚠"])
    def test_text_default_symbols_are_refused_without_their_selector(self, glyph):
        # These are the glyphs whose emoji form REQUIRES the selector the
        # convention forbids, so accepting the bare base would store one
        # thing and render another.
        assert "text-default symbol" in (glyph_contract_error(glyph) or "")

    @pytest.mark.parametrize("glyph", ["", None, 7, []])
    def test_non_glyphs_are_refused(self, glyph):
        assert glyph_contract_error(glyph) is not None


class TestRefusalWording:
    def test_the_refusal_names_the_field_and_offers_safe_glyphs(self):
        with pytest.raises(GlyphContractError) as caught:
            validate_glyph("⚠️", field="level_metadata.X.glyph")
        message = str(caught.value)
        assert message.startswith("level_metadata.X.glyph ")
        for example in SAFE_GLYPH_EXAMPLES:
            assert example in message

    def test_an_unsafe_glyph_is_never_silently_repaired(self):
        # Stripping the selector would store a glyph that looks different
        # from the one the operator typed, which is its own defect.
        with pytest.raises(GlyphContractError):
            validate_glyph("\U0001f3d7️")
