"""Board rendering for a session's level cell.

A level nothing resolved is unroutable — the offer gate refuses to hand work
to it — so it must not read like a configured level on the board. A resolved
level renders with the glyph its project's effective levels give it: the
project's ``session-routing`` override, else the stored universe ``levels``
setting, else the shipped scheme.
"""

from __future__ import annotations

import json

import pytest

from yoke_contracts.board.data import BOARD_DATA_VERSION, ReplayBoardDB
from yoke_contracts.board.sections_sessions import _render_level
from yoke_contracts.board.sections_sessions_levels import _PROJECT_SQL, _UNIVERSE_SQL
from yoke_contracts.board.sections_sessions_scope import session_level_presentation
from yoke_contracts.level_defaults import DEFAULT_LEVELS
from yoke_contracts.levels import LEVELS_KEY, default_levels, level_presentation
from yoke_contracts.project_contract.project_keys import SESSION_ROUTING_CAPABILITY
from yoke_contracts.session_level import UNRESOLVED_EXECUTION_LEVEL

_MARKER = "⚠️"


def _option(model: str) -> dict:
    return {
        "surface": "claude-cli",
        "model": model,
        "reasoning_effort": "high",
        "context_window_tokens": None,
    }


def _research_levels(glyph: str = "\U0001f52c") -> list[dict]:
    return [
        {"name": "RESEARCH", "glyph": glyph, "options": [_option("claude-opus-5-5")]}
    ]


def _replay(*, universe=None, project=None, project_id: int = 1) -> ReplayBoardDB:
    """A board handle serving the two level stores the board reads."""
    entries = []
    if universe is not None:
        entries.append(
            {
                "kind": "query_quiet",
                "sql": _UNIVERSE_SQL,
                "params": [LEVELS_KEY],
                "rows": [[json.dumps(universe)]],
            }
        )
    if project is not None:
        entries.append(
            {
                "kind": "query_quiet",
                "sql": _PROJECT_SQL,
                "params": [project_id, SESSION_ROUTING_CAPABILITY],
                "rows": [[json.dumps(project)]],
            }
        )
    return ReplayBoardDB.from_payload(
        {"version": BOARD_DATA_VERSION, "entries": entries}
    )


@pytest.mark.parametrize("level", [None, "", "   ", "primary", "PRIMARY"])
def test_unresolved_level_is_marked(level) -> None:
    rendered = _render_level(level)
    assert rendered.startswith(_MARKER)
    assert UNRESOLVED_EXECUTION_LEVEL in rendered


@pytest.mark.parametrize("level", ["INTERN", "PRINCIPAL"])
def test_configured_level_renders_without_the_marker(level) -> None:
    rendered = _render_level(level)
    assert _MARKER not in rendered
    assert level in rendered


def test_level_without_an_emoji_still_renders_its_name() -> None:
    assert _render_level("RESEARCH") == "RESEARCH"


def test_shipped_levels_carry_their_glyphs() -> None:
    levels = default_levels()
    assert [level.name for level in levels] == [
        "INTERN",
        "JUNIOR",
        "SENIOR",
        "PRINCIPAL",
    ]
    assert level_presentation(levels, "INTERN") == {
        "label": "INTERN",
        "glyph": "\U0001f423",
    }
    assert level_presentation(levels, "PRINCIPAL") == {
        "label": "PRINCIPAL",
        "glyph": "\U0001f985",
    }


def test_unknown_stamped_level_renders_its_name_and_no_glyph() -> None:
    """A level no effective scheme declares — a retired name included."""
    levels = default_levels()
    for name in ("DARIUS", "RESEARCH"):
        presentation = level_presentation(levels, name)
        assert presentation == {"label": name, "glyph": ""}
        assert _render_level(name, presentation) == name


def test_board_reads_the_shipped_scheme_when_nothing_is_stored() -> None:
    replay = _replay()
    assert session_level_presentation(replay, 1, "SENIOR") == {
        "label": "SENIOR",
        "glyph": "\U0001f989",
    }
    assert session_level_presentation(replay, None, "JUNIOR") == {
        "label": "JUNIOR",
        "glyph": "\U0001f425",
    }


def test_board_reads_the_stored_universe_levels() -> None:
    replay = _replay(universe=_research_levels())
    assert session_level_presentation(replay, 1, "RESEARCH") == {
        "label": "RESEARCH",
        "glyph": "\U0001f52c",
    }
    # The stored universe document replaces the shipped scheme outright.
    assert session_level_presentation(replay, 1, "SENIOR") == {
        "label": "SENIOR",
        "glyph": "",
    }


def test_board_prefers_the_project_override() -> None:
    replay = _replay(
        universe=list(DEFAULT_LEVELS),
        project={LEVELS_KEY: _research_levels("\U0001f680")},
        project_id=7,
    )
    assert session_level_presentation(replay, 7, "RESEARCH") == {
        "label": "RESEARCH",
        "glyph": "\U0001f680",
    }
    assert session_level_presentation(replay, 7, "INTERN") == {
        "label": "INTERN",
        "glyph": "",
    }


def test_project_routing_without_levels_falls_back_to_the_universe() -> None:
    replay = _replay(universe=_research_levels(), project={}, project_id=3)
    assert session_level_presentation(replay, 3, "RESEARCH")["glyph"] == ("\U0001f52c")


def test_unreadable_stored_levels_render_label_only() -> None:
    replay = _replay(universe=[{"name": "bad name", "glyph": "x", "options": []}])
    assert session_level_presentation(replay, 1, "SENIOR") == {
        "label": "SENIOR",
        "glyph": "",
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
    from yoke_contracts.glyph_contract import BOARD_GLYPH_CELLS
    from yoke_contracts.levels import parse_levels

    for glyph in ("\U0001f52c", "\U0001f680", "\U0001f40e"):
        levels = parse_levels(_research_levels(glyph))
        rendered = _render_level("RESEARCH", level_presentation(levels, "RESEARCH"))
        assert rendered == f"{glyph} RESEARCH"
        assert display_width(rendered) == (BOARD_GLYPH_CELLS + 1 + len("RESEARCH"))


def test_every_custom_level_renders_at_the_same_width() -> None:
    """Two levels whose labels match must produce two identical widths.

    This is the alignment the convention exists for: differing glyph widths
    between rows is exactly how a board's columns shear.
    """
    from yoke_contracts.board.utils import display_width
    from yoke_contracts.levels import parse_levels

    widths = set()
    for glyph in ("\U0001f40e", "\U0001f453", "\U0001f6f8", "\U0001f680"):
        levels = parse_levels(
            [{"name": "LEVEL", "glyph": glyph, "options": [_option("claude-opus-5-5")]}]
        )
        widths.add(
            display_width(_render_level("LEVEL", level_presentation(levels, "LEVEL")))
        )
    assert len(widths) == 1
