"""Back-navigation coverage for the ``yoke setup`` wizard.

Esc and Ctrl+[ step back one view. These cases share the pilot scaffolding in
``onboard_wizard_test_helpers`` with the core flow suite in
``test_yoke_operations_cli_onboard_wizard``; they live apart to keep each
module under the per-file line limit.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Static  # noqa: E402

from yoke_cli.config.onboard_wizard_state import _View  # noqa: E402
from yoke_cli.config import onboard_wizard_self_host as self_host  # noqa: E402
from yoke_cli.config.onboard_wizard_widgets import (  # noqa: E402
    STEP_PROJECT,
    SelectionList,
    Stepper,
)
from yoke_cli.config.setup_prompt import SelectionRow, SetupPrompt  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
)
from runtime.api.cli.onboard_wizard_view_test_support import wait_for_view  # noqa: E402


def _prompt() -> SetupPrompt:
    return SetupPrompt(key="test.screen", step=STEP_PROJECT, title="Test screen")


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def test_esc_steps_back_one_view() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")  # machine github: Skip for now
            await pilot.press("enter")
            await wait_for_view(pilot, "project.mode", "SelectionList")
            await pilot.press("down")  # project: move off the default folder row
            await pilot.press("enter")  # -> checkout input
            await wait_for_view(pilot, "project.folder", "Input")
            await pilot.press("escape")  # back to project mode list
            await wait_for_view(pilot, "project.mode", "SelectionList")
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
            await pilot.press("down")  # machine github: Skip for now
            await pilot.press("enter")
            await wait_for_view(pilot, "project.mode", "SelectionList")
            await pilot.press("down")  # project: move off the default folder row
            await pilot.press("enter")  # -> checkout input
            await wait_for_view(pilot, "project.folder", "Input")
            await pilot.press("ctrl+[")  # back to project mode list
            await wait_for_view(pilot, "project.mode", "SelectionList")
            assert app.query_one(Stepper).active == STEP_PROJECT
            lists = app.query("#onboard-body SelectionList")
            assert lists
            assert isinstance(lists.first(), SelectionList)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "route",
    [
        "project-git",
        "clone-git",
        "clone-remote",
        "project-lookup",
        "self-host-preview",
        "self-host-failure",
        "local-summary",
    ],
)
@pytest.mark.parametrize("key", ["escape", "ctrl+[", "enter"])
def test_back_returns_to_exact_previous_view(route: str, key: str) -> None:
    app, _spy = make_app()

    def choose(value: str) -> None:
        if route == "project-git":
            app._on_project_git_missing(value, "clone-remote")
        elif route == "clone-git":
            app._on_clone_missing_git(value, "https://example.com/repo.git")
        elif route == "clone-remote":
            app._on_clone_remote_error(value, "https://example.com/repo.git")
        elif route == "project-lookup":
            app._on_existing_project_lookup_error(value, retry=lambda: None)
        elif route == "self-host-preview":
            self_host._on_preview(app, None, value)
        elif route == "self-host-failure":
            self_host._on_failure(app, None, value, False)
        else:
            app._on_local_universe_summary(value, {})

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            previous = _View(_prompt(), builder=lambda: [Static("Previous screen")])
            app._goto(previous)
            app._goto(
                _View(
                    _prompt(),
                    choose,
                    lambda: [SelectionList([SelectionRow("back", "Back", "")])],
                )
            )
            await pilot.pause()
            depth = len(app._history)
            await pilot.press(key)
            await pilot.pause()
            assert app._history[-1] is previous
            assert len(app._history) == depth - 1
            assert (
                str(app.query_one("#onboard-body Static").render()) == "Previous screen"
            )

    asyncio.run(scenario())


def test_back_stays_at_first_screen_and_during_apply() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            first = app._history[-1]
            await pilot.press("escape")
            assert app._history == [first]
            applying = _View(_prompt(), builder=lambda: [Static("Applying")])
            app._goto(applying)
            await pilot.pause()
            app._applying = True
            await pilot.press("escape", "ctrl+[")
            await pilot.pause()
            assert app._history == [first, applying]
            app._applying = False

    asyncio.run(scenario())


@pytest.mark.parametrize("key", ["escape", "ctrl+[", "enter"])
@pytest.mark.parametrize("error", ["source-checkout", "server-image"])
def test_error_back_keeps_the_screen_that_requested_the_check(
    key: str,
    error: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yoke_cli.config import (
        onboard_self_host_server,
        onboard_wizard_image_repository,
    )

    app, _spy = make_app()

    def refuse_setup(**_kwargs):
        raise ValueError("image_repository_invalid: choose a valid image repository")

    monkeypatch.setattr(onboard_self_host_server, "new_setup", refuse_setup)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            previous = _View(_prompt(), builder=lambda: [Static("Requested check here")])
            app._goto(previous)
            if error == "source-checkout":
                app._goto_dev_error("source_checkout_invalid: choose a source checkout")
            else:
                assert onboard_wizard_image_repository.load_setup(app) is None
            await pilot.pause()
            await pilot.press(key)
            await pilot.pause()
            assert app._history[-1] is previous
            assert len(app._history) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("key", ["escape", "ctrl+[", "enter"])
def test_apply_outcome_back_returns_to_the_preceding_interactive_view(key: str) -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            review = _View(_prompt(), builder=lambda: [Static("Review setup")])
            app._goto(review)
            app._goto_applying()
            app._replace_current(
                _View(
                    _prompt(),
                    app._on_apply_failure,
                    lambda: [
                        SelectionList([SelectionRow("back", "Change answers", "")])
                    ],
                )
            )
            await pilot.pause()
            await pilot.press(key)
            await pilot.pause()
            assert app._history[-1] is review
            assert len(app._history) == 2

    asyncio.run(scenario())
