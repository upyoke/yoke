"""Back-navigation coverage for the ``yoke onboard`` wizard.

Esc and Ctrl+[ step back one view. These cases share the pilot scaffolding in
``onboard_wizard_test_helpers`` with the core flow suite in
``test_yoke_operations_cli_onboard_wizard``; they live apart to keep each
module under the per-file line limit.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_cli.config.onboard_wizard_widgets import (  # noqa: E402
    STEP_PROJECT,
    SelectionList,
    Stepper,
)

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def test_esc_steps_back_one_view() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")     # machine github: Skip for now
            await pilot.press("enter")
            await pilot.press("down")     # project: move off the default folder row
            await pilot.press("enter")    # -> checkout input
            await pilot.press("escape")   # back to project mode list
            await pilot.pause()
            assert app.query_one(Stepper).active == STEP_PROJECT
            lists = app.query("#onboard-body SelectionList")
            assert lists
            assert isinstance(lists.first(), SelectionList)

    asyncio.run(scenario())


def test_ctrl_left_bracket_steps_back_one_view() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")        # machine github: Skip for now
            await pilot.press("enter")
            await pilot.press("down")        # project: move off the default folder row
            await pilot.press("enter")       # -> checkout input
            await pilot.press("ctrl+[")      # back to project mode list
            await pilot.pause()
            assert app.query_one(Stepper).active == STEP_PROJECT
            lists = app.query("#onboard-body SelectionList")
            assert lists
            assert isinstance(lists.first(), SelectionList)

    asyncio.run(scenario())
