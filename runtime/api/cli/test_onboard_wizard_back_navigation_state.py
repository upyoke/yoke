"""Setup wizard state that must survive Back: the rail, Review, typed folders."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Input, Static  # noqa: E402

from yoke_cli.config.onboard_wizard_state import _View  # noqa: E402
from yoke_cli.config.onboard_wizard_widgets import (  # noqa: E402
    STEP_CONNECT,
    STEP_PROJECT,
    SelectionList,
    Stepper,
    stepper_mark,
)
from yoke_cli.config.setup_prompt import SetupPrompt  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
    type_text,
)
from runtime.api.cli.onboard_wizard_view_test_support import wait_for_view  # noqa: E402

_PLAN = {
    "plan": {
        "reuse": {"token_reference": True},
        "steps": [
            {"action": "reuse-session-relay-token", "target": "existing-api-token"},
            {"action": "set-active-env", "target": "prod"},
        ],
    }
}


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def _row_labels(app) -> list[str]:
    chooser = app.query_one("#onboard-body SelectionList", SelectionList)
    return [row.label for row in chooser.rows]


def test_project_type_before_sign_in_keeps_account_active() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._goto_project_mode(on_selected=app._remember_project_mode)
            await app._apply_pending_swap()
            await wait_for_view(pilot, "project.mode", "SelectionList")
            stepper = app.query_one(Stepper)
            assert stepper.active == STEP_CONNECT
            assert (
                stepper_mark(STEP_CONNECT, active=stepper.active, github_complete=False)
                == "active"
            )
            assert (
                stepper_mark(STEP_PROJECT, active=stepper.active, github_complete=False)
                == "pending"
            )

    asyncio.run(scenario())


def test_esc_from_show_all_changes_returns_to_review_summary() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test(size=(160, 60)) as pilot:
            await pilot.pause()
            app._goto(
                _View(
                    SetupPrompt(
                        key="hosting.provider", step=STEP_PROJECT, title="Hosting"
                    ),
                    builder=lambda: [Static("Hosting")],
                )
            )
            app._show_finish({"plan": _PLAN})
            await app._apply_pending_swap()
            await pilot.pause()
            summary = app._history[-1]
            assert "Show all changes" in _row_labels(app)
            app._on_confirm("show-all")
            await app._apply_pending_swap()
            await pilot.pause()
            assert "Show summary" in _row_labels(app)
            await pilot.press("escape")
            await pilot.pause()
            assert app._history[-1] is summary
            assert app._history[-1].prompt.key == "review.confirm"
            assert "Show all changes" in _row_labels(app)

    asyncio.run(scenario())


def test_show_summary_returns_to_the_same_review_view() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test(size=(160, 60)) as pilot:
            await pilot.pause()
            app._show_finish({"plan": _PLAN})
            await app._apply_pending_swap()
            summary, depth = app._history[-1], len(app._history)
            app._on_confirm("show-all")
            await app._apply_pending_swap()
            app._history[-1].on_select("show-all")
            await app._apply_pending_swap()
            await pilot.pause()
            assert app._history[-1] is summary
            assert len(app._history) == depth
            assert "Show all changes" in _row_labels(app)

    asyncio.run(scenario())


def test_typed_folder_survives_esc_and_forward_again() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")  # machine github: Skip for now
            await pilot.press("enter")
            await wait_for_view(pilot, "project.mode", "SelectionList")
            await pilot.press("down")  # project: point at an existing folder
            await pilot.press("enter")
            await wait_for_view(pilot, "project.folder", "Input")
            await type_text(pilot, "~/code/kept")
            await pilot.press("escape")
            await wait_for_view(pilot, "project.mode", "SelectionList")
            await pilot.press("enter")  # same row again
            await wait_for_view(pilot, "project.folder", "Input")
            assert app.query_one("#onboard-input", Input).value == "~/code/kept"

    asyncio.run(scenario())


def test_typed_clone_folder_survives_back_and_return() -> None:
    app, _spy = make_app()
    app.result.project_remote_url = "https://github.com/acme/widgets.git"

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app._goto(
                _View(
                    SetupPrompt(
                        key="test.previous", step=STEP_PROJECT, title="Previous"
                    ),
                    builder=lambda: [Static("Previous")],
                )
            )
            app._goto_clone_folder()
            await wait_for_view(pilot, "project.clone_folder", "Input")
            await type_text(pilot, "~/code/my-widgets")
            await pilot.press("escape")
            await pilot.pause()
            assert app._history[-1].prompt.key == "test.previous"
            app._goto_clone_folder()
            await wait_for_view(pilot, "project.clone_folder", "Input")
            assert app.query_one("#onboard-input", Input).value == "~/code/my-widgets"

    asyncio.run(scenario())
