"""A scroll resting between two cells must not change the exported screen.

A container draws its text at ``round(scroll_y)`` and its scrollbar at the raw
float. So a scroll stopped part-way through a cell exports the same text beside
a thumb whose tail has crossed into the next cell — one extra partial glyph and
one extra style rule, on a screen that is otherwise correct. That is a golden
gate failing on where a scroll came to rest rather than on what the wizard drew.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("textual")

from runtime.api.cli.onboard_wizard_golden_capture import (  # noqa: E402
    _stable_screenshot,
    snap_scroll_offsets,
)
from runtime.api.cli.onboard_wizard_golden_support import (  # noqa: E402
    FINISH_PLAN_FULL,
    TERMINAL_SIZE,
    golden_color_env,
    make_app,
)
from yoke_cli.config import project_git_probe  # noqa: E402
from yoke_cli.config import project_git_transport  # noqa: E402

# Far enough into the cell to move the scrollbar thumb, near enough that the
# content still rounds to the row it already occupies.
SUB_CELL_NUDGE = 0.2


class _Widget:
    def __init__(self, scroll_x: float, scroll_y: float) -> None:
        self.scroll_x = scroll_x
        self.scroll_y = scroll_y


class _Screen(_Widget):
    def __init__(self, children: list[_Widget]) -> None:
        super().__init__(0.0, 0.0)
        self._children = children

    def query(self, _selector: str) -> list[_Widget]:
        return self._children


class _App:
    def __init__(self, screen: _Screen) -> None:
        self.screen = screen


def test_snaps_to_the_row_the_content_already_draws() -> None:
    # Rounding, not truncation: the content at scroll_y 1.8 is already drawn on
    # row 2, so truncating to 1 would move the text this snap exists to leave
    # alone.
    body = _Widget(0.0, 1.8)
    screen = _Screen([body])

    snap_scroll_offsets(_App(screen))

    assert (body.scroll_x, body.scroll_y) == (0, 2)


def test_snaps_the_screen_itself_not_only_its_children() -> None:
    screen = _Screen([])
    screen.scroll_y = 3.4

    snap_scroll_offsets(_App(screen))

    assert screen.scroll_y == 3


@pytest.fixture
def _stub_source_branch(monkeypatch):
    monkeypatch.setattr(
        project_git_transport,
        "remote_probe",
        lambda url, token=None, github_web_url=None: project_git_probe.GitRemoteProbe(
            True, default_branch="main",
        ),
    )
    monkeypatch.setattr(
        project_git_transport, "remote_default_branch",
        lambda url, token=None, github_web_url=None: "main",
    )


def test_export_survives_a_scroll_resting_between_cells(_stub_source_branch) -> None:
    """The Review screen exports the same bytes with a sub-cell scroll pending.

    Review is the screen that overflows its body far enough to carry a
    scrollbar, so it is the one where a mid-cell scroll can reach the export.
    """
    app = make_app(apply_report=lambda _kw: FINISH_PLAN_FULL)
    title = "yoke onboard · Review"

    async def scenario() -> tuple[str, str, float]:
        async with app.run_test(size=TERMINAL_SIZE) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            app._goto_finish()
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.pause()
            body = app.query_one("#onboard-body")
            settled = await _stable_screenshot(pilot, app, title)

            # Leave the scroll part-way through a cell, the state an animated
            # scroll passes through on a runner too busy to finish it.
            body.scroll_y = body.scroll_y - SUB_CELL_NUDGE
            await pilot.pause()
            resting = await _stable_screenshot(pilot, app, title)
            return settled, resting, body.scroll_y

    with golden_color_env():
        settled, resting, scroll_y = asyncio.run(scenario())

    assert resting == settled
    assert scroll_y == int(scroll_y), "capture left the scroll between two cells"


def test_animations_resolve_instantly_rather_than_over_wall_clock() -> None:
    """An animated scroll must land on its target before the next export.

    Interpolating against the clock is what puts a scroll between two cells in
    the first place; this pins the setting that removes the source.
    """
    app: Any = make_app()

    assert app.animation_level == "none"
