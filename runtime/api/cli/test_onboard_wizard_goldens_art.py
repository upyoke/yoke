"""Textual SVG golden gates for the board-art onboarding screens.

Each gate drives the real flow to one board-art screen and asserts its exported
SVG byte-for-byte against ``__snapshots__``. Art generation is seeded off the
stubbed project slug, so the ASCII/Mixed renders are deterministic; the
master-map preview and payoff render through the real frontier fill with the
fixed simulated counts. These are the first emoji-bearing goldens in the tree —
bless them with YOKE_WIZARD_GOLDEN_UPDATE=1 after eyeballing alignment.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("textual")

from runtime.api.cli.onboard_wizard_golden_support import (  # noqa: E402
    assert_golden,
    make_app,
    render,
)

_TITLE = "yoke onboard · Board art"


def _seed_project(app: Any) -> None:
    app.result.project_name = "Buzz"
    app.result.project_slug = "buzz"
    app.result.project_public_item_prefix = "BUZZ"


def test_art_intro() -> None:
    app = make_app()

    async def drive(a: Any, _pilot: Any) -> None:
        _seed_project(a)
        a._goto_board_art_intro()

    assert_golden("art_intro", render(app, drive, title=_TITLE))


def test_art_map_preview() -> None:
    app = make_app()

    async def drive(a: Any, _pilot: Any) -> None:
        _seed_project(a)
        a._goto_board_art_intro()
        a._on_board_art_intro("design")

    assert_golden("art_map_preview", render(app, drive, title=_TITLE))


def test_art_style() -> None:
    app = make_app()

    async def drive(a: Any, _pilot: Any) -> None:
        _seed_project(a)
        a._goto_board_art_intro()
        a._on_board_art_intro("design")
        a._on_board_art_map_preview("continue")

    assert_golden("art_style", render(app, drive, title=_TITLE))


def test_art_ascii_preview() -> None:
    app = make_app()

    async def drive(a: Any, _pilot: Any) -> None:
        _seed_project(a)
        a._goto_board_art_intro()
        a._on_board_art_intro("design")
        a._on_board_art_map_preview("continue")
        a._on_board_art_style("ascii")

    assert_golden("art_ascii_preview", render(app, drive, title=_TITLE))


def test_art_mixed_preview() -> None:
    app = make_app()

    async def drive(a: Any, _pilot: Any) -> None:
        _seed_project(a)
        a._goto_board_art_intro()
        a._on_board_art_intro("design")
        a._on_board_art_map_preview("continue")
        a._on_board_art_style("mixed")

    assert_golden("art_mixed_preview", render(app, drive, title=_TITLE))


def test_art_gallery() -> None:
    app = make_app()

    async def drive(a: Any, _pilot: Any) -> None:
        _seed_project(a)
        a._goto_board_art_intro()
        a._on_board_art_intro("design")
        a._on_board_art_map_preview("continue")
        a._on_board_art_style("ascii")
        a._on_board_art_preview("save")

    assert_golden("art_gallery", render(app, drive, title=_TITLE))


def test_art_payoff() -> None:
    app = make_app()

    async def drive(a: Any, _pilot: Any) -> None:
        _seed_project(a)
        a._goto_board_art_intro()
        a._on_board_art_style("ascii")
        a._on_board_art_preview("save")
        a._goto_board_art_payoff()

    assert_golden("art_payoff", render(app, drive, title="yoke onboard · Done"))
