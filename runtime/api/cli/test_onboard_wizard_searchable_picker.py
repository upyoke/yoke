"""Keyboard and viewport coverage for onboarding's searchable long-list picker."""

from __future__ import annotations

import asyncio

import pytest
from textual.widgets import Static

pytest.importorskip("textual")

from runtime.api.cli.onboard_wizard_golden_support import make_app  # noqa: E402
from yoke_cli.config import github_publish  # noqa: E402
from yoke_cli.config.onboard_wizard_searchable_picker import (  # noqa: E402
    SearchableSelectionList,
)
from yoke_cli.config.onboard_wizard_widgets import (  # noqa: E402
    _OptionRow,
    _SelectionDescription,
)


def _owners(count: int = 12) -> list[github_publish.RepoOwner]:
    return [
        github_publish.RepoOwner(
            login=f"account-{index:02d}",
            kind="user" if index == 0 else "organization",
        )
        for index in range(count)
    ]


def _text(widget: Static) -> str:
    rendered = widget.content
    return getattr(rendered, "plain", str(rendered))


def test_long_picker_starts_at_top_and_scrolls_without_typing() -> None:
    app = make_app()

    async def scenario() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            app._show_owner_picker(_owners())
            await pilot.pause()
            picker = app.query_one(SearchableSelectionList)

            assert picker.selected_value == "account-00"
            assert len(list(picker.query(_OptionRow))) == 8
            assert "12 results" in _text(
                app.query_one("#onboard-search-status", Static)
            )

            for _ in range(9):
                await pilot.press("down")
            assert picker.selected_value == "account-09"
            assert picker._window_start == 2
            assert "organization" in _text(
                app.query_one(_SelectionDescription)
            )

    asyncio.run(scenario())


def test_typing_filters_and_clear_restores_the_complete_list() -> None:
    app = make_app()

    async def scenario() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            app._show_owner_picker(_owners())
            await pilot.pause()
            picker = app.query_one(SearchableSelectionList)

            await pilot.press("1")
            await pilot.pause()
            assert [row.value for row in picker.rows] == [
                "account-01", "account-10", "account-11",
            ]
            assert "3 results" in _text(
                app.query_one("#onboard-search-status", Static)
            )

            await pilot.press("ctrl+u")
            await pilot.pause()
            assert len(picker.rows) == 12
            assert picker.selected_value == "account-00"
            assert "12 results" in _text(
                app.query_one("#onboard-search-status", Static)
            )

    asyncio.run(scenario())


def test_no_match_state_is_bounded_and_explains_how_to_recover() -> None:
    app = make_app()

    async def scenario() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            app._show_owner_picker(_owners(3))
            await pilot.pause()
            picker = app.query_one(SearchableSelectionList)

            await pilot.press("z", "z", "z")
            await pilot.pause()
            assert picker.rows == []
            assert "0 results" in _text(
                app.query_one("#onboard-search-status", Static)
            )
            assert "Clear the filter" in _text(
                app.query_one(_SelectionDescription)
            )
            assert len(list(picker.query(_OptionRow))) == 8

    asyncio.run(scenario())
