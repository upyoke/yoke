"""Board rendering for a session's level cell.

A level nothing resolved is unroutable — the offer gate refuses to hand work
to it — so it must not read like a configured level on the board.
"""

from __future__ import annotations

import pytest

from yoke_contracts.board.data import BOARD_DATA_VERSION, ReplayBoardDB
from yoke_contracts.board.sections_sessions import _render_level
from yoke_contracts.board.sections_sessions_scope import session_level_presentation
from yoke_contracts.session_level import (
    UNRESOLVED_EXECUTION_LEVEL,
    level_presentation,
)

_MARKER = "⚠️"


@pytest.mark.parametrize("level", [None, "", "   ", "primary", "PRIMARY"])
def test_unresolved_level_is_marked(level) -> None:
    rendered = _render_level(level)
    assert rendered.startswith(_MARKER)
    assert UNRESOLVED_EXECUTION_LEVEL in rendered


@pytest.mark.parametrize("level", ["DARIUS", "ALTMAN"])
def test_configured_level_renders_without_the_marker(level) -> None:
    rendered = _render_level(level)
    assert _MARKER not in rendered
    assert level in rendered


def test_level_without_an_emoji_still_renders_its_name() -> None:
    assert _render_level("RESEARCH") == "RESEARCH"


def test_operator_defined_level_presentation_travels_with_routing_settings() -> None:
    presentation = level_presentation(
        "RESEARCH",
        {"level_metadata": {"RESEARCH": {"label": "Research", "glyph": "🔬"}}},
    )
    assert presentation == {"label": "Research", "glyph": "🔬"}
    assert _render_level("RESEARCH", presentation) == "🔬 Research"


def test_original_level_presentation_is_an_exact_legacy_fallback() -> None:
    assert level_presentation("DARIUS", {}) == {"label": "DARIUS", "glyph": "🐎"}
    assert level_presentation("RESEARCH", {}) == {"label": "RESEARCH", "glyph": ""}


def test_legacy_board_payload_uses_level_presentation_fallback() -> None:
    replay = ReplayBoardDB.from_payload({"version": BOARD_DATA_VERSION, "entries": []})

    assert session_level_presentation(replay, 1, "DARIUS") == {
        "label": "DARIUS",
        "glyph": "🐎",
    }


def test_a_custom_level_glyph_occupies_one_board_column() -> None:
    """The write-time contract and the renderer must agree on the width.

    Measuring with the renderer's own helper rather than a string length is
    the point: the helper consumes selector and modifier sequences that the
    source convention forbids, so a glyph that passes a length check can
    still shear the column. Only glyphs the write boundary accepts are
    asserted here, because only those can reach a level.
    """
    from yoke_contracts.board.utils import display_width
    from yoke_contracts.glyph_contract import BOARD_GLYPH_CELLS, validate_glyph

    for glyph in ("\U0001f52c", "\U0001f680", "\U0001f40e"):
        validate_glyph(glyph)
        presentation = level_presentation(
            "RESEARCH",
            {"level_metadata": {"RESEARCH": {"label": "RESEARCH", "glyph": glyph}}},
        )
        rendered = _render_level("RESEARCH", presentation)
        assert rendered == f"{glyph} RESEARCH"
        assert display_width(rendered) == (BOARD_GLYPH_CELLS + 1 + len("RESEARCH"))


def test_every_custom_level_renders_at_the_same_width() -> None:
    """Two levels whose labels match must produce two identical widths.

    This is the alignment the convention exists for: differing glyph widths
    between rows is exactly how a board's columns shear.
    """
    from yoke_contracts.board.utils import display_width

    widths = {
        display_width(
            _render_level(
                "LEVEL",
                level_presentation(
                    "LEVEL",
                    {"level_metadata": {"LEVEL": {"label": "LEVEL", "glyph": glyph}}},
                ),
            )
        )
        for glyph in ("\U0001f40e", "\U0001f453", "\U0001f6f8", "\U0001f680")
    }
    assert len(widths) == 1
