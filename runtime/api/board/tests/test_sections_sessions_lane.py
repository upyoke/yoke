"""Board rendering for a session's lane cell.

A lane nothing resolved is unroutable — the offer gate refuses to hand work
to it — so it must not read like a configured lane on the board.
"""

from __future__ import annotations

import pytest

from yoke_contracts.board.sections_sessions import _render_lane
from yoke_contracts.session_lane import UNRESOLVED_EXECUTION_LANE

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
