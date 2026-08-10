"""A scrollbar must be drawn from the same layout pass as the text beside it.

A scrollbar keeps its own copies of its container's virtual size, window size
and position, and Textual refreshes them only when the container's own
measurements change. A copy carried over from an earlier layout renders a thumb
that disagrees with the text: a virtual size one row too tall stops the thumb
short of the track, and the reversed end-cap glyph that appears there paints in
the scrollbar's background colour — a colour no other element on the screen
uses, so the export carries one extra style rule while every character matches.
That is a golden gate failing on which pass drew the thumb rather than on what
the wizard drew.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from runtime.api.cli.onboard_wizard_golden_capture import (  # noqa: E402
    compose_frame,
    sync_scrollbar_geometry,
)
from runtime.api.cli.onboard_wizard_golden_support import (  # noqa: E402
    FINISH_PLAN_FULL,
    TERMINAL_SIZE,
    golden_color_env,
    make_app,
)
from yoke_cli.config import project_git_probe  # noqa: E402
from yoke_cli.config import project_git_transport  # noqa: E402

TITLE = "yoke onboard · Review"

# One row taller than the body actually is — the stale copy that stops the thumb
# short of the track end and adds the end-cap glyph.
STALE_VIRTUAL_HEIGHT_OFFSET = 1


class _Size:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height


class _Bar:
    def __init__(self) -> None:
        self.window_virtual_size = 0
        self.window_size = 0
        self.position = 0.0


class _Body:
    is_scrollable = True
    show_vertical_scrollbar = True
    show_horizontal_scrollbar = False
    scrollbar_size_horizontal = 0
    scrollbar_size_vertical = 2
    scroll_x = 0.0
    scroll_y = 2.0
    virtual_size = _Size(95, 25)
    container_size = _Size(97, 23)

    def __init__(self) -> None:
        self.vertical_scrollbar = _Bar()


class _Screen:
    is_scrollable = False
    scroll_x = 0
    scroll_y = 0

    def __init__(self, children: list[_Body]) -> None:
        self._children = children

    def query(self, _selector: str) -> list[_Body]:
        return self._children

    def _refresh_layout(self) -> None:
        return None


class _App:
    focused = None

    def __init__(self, screen: _Screen) -> None:
        self.screen = screen

    def export_screenshot(self, *, title: str) -> str:
        return title


def _stale_body() -> _Body:
    body = _Body()
    body.vertical_scrollbar.window_virtual_size = (
        body.virtual_size.height + STALE_VIRTUAL_HEIGHT_OFFSET
    )
    return body


def test_restates_a_scrollbar_copy_left_over_from_an_earlier_layout() -> None:
    body = _stale_body()

    sync_scrollbar_geometry(_App(_Screen([body])))

    bar = body.vertical_scrollbar
    assert bar.window_virtual_size == body.virtual_size.height
    assert bar.window_size == body.container_size.height
    assert bar.position == body.scroll_y


def test_composing_a_frame_restates_the_geometry_before_exporting() -> None:
    # Textual reconciles a scrollbar only when the container's own measurements
    # change, so a copy that is stale on its own is one a reflow can walk past.
    # Composing a frame has to restate it rather than hope the reflow does.
    body = _stale_body()

    compose_frame(_App(_Screen([body])), "t")

    assert body.vertical_scrollbar.window_virtual_size == body.virtual_size.height


@pytest.fixture
def _stub_source_branch(monkeypatch):
    monkeypatch.setattr(
        project_git_transport,
        "remote_probe",
        lambda url, token=None, github_web_url=None: project_git_probe.GitRemoteProbe(
            True,
            default_branch="main",
        ),
    )
    monkeypatch.setattr(
        project_git_transport, "remote_default_branch",
        lambda url, token=None, github_web_url=None: "main",
    )


def _review_app():
    return make_app(apply_report=lambda _kw: FINISH_PLAN_FULL)


def test_export_survives_a_scrollbar_left_behind_by_an_earlier_layout(
    _stub_source_branch,
) -> None:
    """Review is the screen that overflows its body far enough to carry a
    scrollbar, so it is the one where a stale copy can reach the export."""
    app = _review_app()

    async def scenario() -> tuple[str, str]:
        async with app.run_test(size=TERMINAL_SIZE) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            app._goto_finish()
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.pause()
            settled = compose_frame(app, TITLE)

            body = app.query_one("#onboard-body")
            body.vertical_scrollbar.window_virtual_size = (
                body.virtual_size.height + STALE_VIRTUAL_HEIGHT_OFFSET
            )
            await pilot.pause()
            return settled, compose_frame(app, TITLE)

    with golden_color_env():
        settled, stale = asyncio.run(scenario())

    assert stale == settled


def test_a_scroll_reaches_the_export_without_waiting_for_the_next_turn(
    _stub_source_branch,
) -> None:
    """Composing the frame is what puts the scroll in it, not a pause.

    Textual recomposes on the next turn of the message loop, so an export taken
    straight after a scroll otherwise shows the moved thumb beside unmoved text
    — a frame that can repeat often enough to be mistaken for a settled one.
    """
    app = _review_app()

    async def scenario() -> tuple[str, str]:
        async with app.run_test(size=TERMINAL_SIZE) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            app._goto_finish()
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.pause()
            # The body rests unscrolled until the viewport is aimed at the
            # control the screen focused on mount.
            immediate = compose_frame(app, TITLE)
            await pilot.pause()
            return immediate, compose_frame(app, TITLE)

    with golden_color_env():
        immediate, after_a_turn = asyncio.run(scenario())

    assert immediate == after_a_turn
