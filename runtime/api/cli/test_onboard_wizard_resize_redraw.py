"""Every setup screen appears exactly once, across view changes and resizes.

The wizard runs on a driver that writes its real escape output into a no-wrap
terminal model. After each step the terminal must match, cell for cell, what
Textual believes is on screen: the current title once, no earlier screen
underneath, and the header pinned to its row.
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytest.importorskip("textual")

from textual.events import Resize  # noqa: E402
from textual.geometry import Size  # noqa: E402
from textual.widgets import Static  # noqa: E402

from yoke_cli.config import onboard_terminal_driver  # noqa: E402
from yoke_cli.config.onboard_wizard_redraw import RESET_AND_ERASE_SCREEN  # noqa: E402

from runtime.api.cli.onboard_terminal_model import (  # noqa: E402
    TerminalModel,
    expected_screen,
    terminal_driver,
)
from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    skip_hosting,
    stub_path_doctor,
    type_text,
)

HEADER_TEXT = "Yoke  · Set up your machine and onboard your projects"
WIDE, NARROW, SHORT = (171, 43), (134, 37), (100, 30)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def _wizard_on_terminal(size: tuple[int, int]):
    app, spy = make_app()
    terminal = TerminalModel(*size)
    app.driver_class = terminal_driver(terminal)
    return app, spy, terminal


def _title(app) -> str:
    return str(app.query_one("#onboard-body .onboard-title", Static).render())


async def _resize(pilot, terminal: TerminalModel, size: tuple[int, int]) -> None:
    """Resize the window and post the resize without letting the app settle."""
    terminal.resize(*size)
    pilot.app._driver._size = Size(*size)
    pilot.app.post_message(Resize(Size(*size), Size(*size)))


def _resize_during_next_swap(
    app, terminal: TerminalModel, size: tuple[int, int]
) -> None:
    """Deliver a resize to the screen while the next body swap is batched."""
    body = app.query_one("#onboard-body")
    mount = body.mount

    async def mount_after_resize(*widgets, **kwargs):
        body.mount = mount
        terminal.resize(*size)
        app._driver._size = Size(*size)
        app.post_message(Resize(Size(*size), Size(*size)))
        app.screen.post_message(Resize(Size(*size), Size(*size)))
        await asyncio.sleep(0.05)
        return await mount(*widgets, **kwargs)

    body.mount = mount_after_resize


async def _assert_screen_once(pilot, terminal: TerminalModel, seen: list[str]) -> None:
    await pilot.pause(0.05)
    await pilot.pause()
    app = pilot.app
    expected = expected_screen(app)
    assert (terminal.width, terminal.height) == (expected.width, expected.height)
    assert terminal.rows == expected.rows, (
        "terminal diverged from the wizard's screen:\n"
        + terminal.text
        + "\n--- expected ---\n"
        + expected.text
    )
    title = _title(app)
    seen.append(title)
    assert terminal.text.count(title) == 1, terminal.text
    for earlier in seen:
        assert terminal.text.count(earlier) == expected.text.count(earlier)
    assert HEADER_TEXT in terminal.rows[1], terminal.text


def test_resizing_mid_flow_shows_each_screen_once() -> None:
    app, spy, terminal = _wizard_on_terminal(WIDE)
    seen: list[str] = []

    async def scenario() -> None:
        async with app.run_test(headless=False, size=WIDE) as pilot:
            await _assert_screen_once(pilot, terminal, seen)
            await advance_past_path(pilot)
            await _assert_screen_once(pilot, terminal, seen)  # Connect GitHub?
            await _resize(pilot, terminal, NARROW)
            await _assert_screen_once(pilot, terminal, seen)
            _resize_during_next_swap(app, terminal, SHORT)
            await pilot.press("down", "enter")  # github: Skip for now
            await _assert_screen_once(pilot, terminal, seen)
            await _resize(pilot, terminal, WIDE)
            await pilot.press("enter")  # existing folder, resized mid-transition
            await _assert_screen_once(pilot, terminal, seen)  # project folder
            await type_text(pilot, "/home/code/widget")
            await _resize(pilot, terminal, SHORT)
            await pilot.press("enter", "enter", "enter", "enter", "enter")
            await _assert_screen_once(pilot, terminal, seen)  # publish
            await pilot.press("enter")  # publish: No — keep local (preselected)
            await _resize(pilot, terminal, NARROW)
            await _assert_screen_once(pilot, terminal, seen)  # hosting list
            await _resize(pilot, terminal, WIDE)
            await skip_hosting(pilot)
            await _assert_screen_once(pilot, terminal, seen)  # finish
            await _resize(pilot, terminal, NARROW)
            await pilot.press("enter")  # finish: apply
            await _assert_screen_once(pilot, terminal, seen)  # apply result

    asyncio.run(scenario())

    assert spy.applied is not None
    assert len(set(seen)) >= 6


def test_every_view_change_erases_the_terminal_before_repainting() -> None:
    app, _spy, terminal = _wizard_on_terminal(NARROW)
    writes: list[str] = []
    feed = terminal.feed

    def record(data: str) -> None:
        writes.append(data)
        feed(data)

    terminal.feed = record

    async def scenario() -> None:
        async with app.run_test(headless=False, size=NARROW) as pilot:
            await advance_past_path(pilot)
            writes.clear()
            app._goto_path_apply_error("Install failed; retry after repair.")
            await pilot.pause()
            assert "Retry Install" in terminal.text

    asyncio.run(scenario())

    output = "".join(writes)
    assert RESET_AND_ERASE_SCREEN in output
    assert "Retry Install" in output.split(RESET_AND_ERASE_SCREEN)[-1]


def test_frame_dropped_inside_a_batch_is_repainted() -> None:
    """Textual drops frames painted while updates are batched; a resize whose
    layout lands inside the wizard's body swap paints exactly such a frame."""
    app, _spy, terminal = _wizard_on_terminal(NARROW)

    async def scenario() -> None:
        async with app.run_test(headless=False, size=NARROW) as pilot:
            await pilot.pause()
            title = app.query_one("#onboard-body .onboard-title", Static)
            with app.batch_update():
                title.update("Replaced while batched")
                await pilot.pause()
                app.screen._refresh_layout()
                await pilot.pause()
            await pilot.pause()
            assert terminal.rows == expected_screen(app).rows, terminal.text
            assert terminal.text.count("Replaced while batched") == 1

    asyncio.run(scenario())


def test_wizard_ignores_exported_terminal_geometry(monkeypatch) -> None:
    monkeypatch.setenv("COLUMNS", "171")
    monkeypatch.setenv("LINES", "43")
    observed: dict[str, str | None] = {}

    def run(_app) -> None:
        observed.update({name: os.environ.get(name) for name in ("COLUMNS", "LINES")})

    monkeypatch.setattr(onboard_terminal_driver, "_run_with_platform_driver", run)
    onboard_terminal_driver.run_wizard_app(object())

    assert observed == {"COLUMNS": None, "LINES": None}
    assert (os.environ["COLUMNS"], os.environ["LINES"]) == ("171", "43")
