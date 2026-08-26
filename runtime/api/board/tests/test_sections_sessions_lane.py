"""Board rendering for a session's lane cell.

A lane nothing resolved is unroutable — the offer gate refuses to hand work
to it — so it must not read like a configured lane on the board.
"""

from __future__ import annotations

import pytest

from yoke_contracts.board.data import BOARD_DATA_VERSION, ReplayBoardDB
from yoke_contracts.board.sections_sessions import _render_lane
from yoke_contracts.board.sections_sessions_scope import session_lane_presentation
from yoke_contracts.session_lane import (
    UNRESOLVED_EXECUTION_LANE,
    lane_presentation,
)

_MARKER = "⚠️"


@pytest.mark.parametrize("lane", [None, "", "   ", "primary", "PRIMARY"])
def test_unresolved_lane_is_marked(lane) -> None:
    rendered = _render_lane(lane)
    assert rendered.startswith(_MARKER)
    assert UNRESOLVED_EXECUTION_LANE in rendered


@pytest.mark.parametrize("lane", ["DARIUS", "ALTMAN"])
def test_configured_lane_renders_without_the_marker(lane) -> None:
    rendered = _render_lane(lane)
    assert _MARKER not in rendered
    assert lane in rendered


def test_lane_without_an_emoji_still_renders_its_name() -> None:
    assert _render_lane("RESEARCH") == "RESEARCH"


def test_operator_defined_lane_presentation_travels_with_routing_settings() -> None:
    presentation = lane_presentation(
        "RESEARCH",
        {"lane_metadata": {"RESEARCH": {"label": "Research", "glyph": "🔬"}}},
    )
    assert presentation == {"label": "Research", "glyph": "🔬"}
    assert _render_lane("RESEARCH", presentation) == "🔬 Research"


def test_original_lane_presentation_is_an_exact_legacy_fallback() -> None:
    assert lane_presentation("DARIUS", {}) == {"label": "DARIUS", "glyph": "🐎"}
    assert lane_presentation("RESEARCH", {}) == {"label": "RESEARCH", "glyph": ""}


def test_legacy_board_payload_uses_lane_presentation_fallback() -> None:
    replay = ReplayBoardDB.from_payload({"version": BOARD_DATA_VERSION, "entries": []})

    assert session_lane_presentation(replay, 1, "DARIUS") == {
        "label": "DARIUS",
        "glyph": "🐎",
    }
