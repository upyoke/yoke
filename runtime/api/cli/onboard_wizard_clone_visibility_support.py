"""Shared interaction helpers for clone-visibility wizard coverage."""

from __future__ import annotations

from yoke_cli.config import onboard_github_copy
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard_widgets import SelectionList

from runtime.api.cli.onboard_wizard_github_app_test_support import (
    connect_github_app,
)
from runtime.api.cli.onboard_wizard_test_helpers import advance_past_path


async def pick_mode(pilot, value: str) -> None:
    """Choose one onboarding project mode."""
    index = next(i for i, row in enumerate(steps.MODE_ROWS) if row.value == value)
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")


async def skip_machine_github(pilot) -> None:
    """Reach the project mode chooser without connecting a GitHub App."""
    await advance_past_path(pilot)
    await pilot.press("down")
    await pilot.press("enter")


def body_text(app) -> str:
    """Return the visible onboarding body text."""
    from textual.widgets import Static

    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


async def wait_for_body_text(app, pilot, expected: str) -> str:
    """Wait for one asynchronous wizard body update."""
    for _ in range(10):
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = body_text(app)
        if expected in text:
            return text
    return body_text(app)


async def wait_for_selection(app, pilot) -> SelectionList:
    """Wait for the wizard to render its current selection list."""
    for _ in range(10):
        await app.workers.wait_for_complete()
        await pilot.pause()
        selections = list(
            app.query("#onboard-body SelectionList").results(SelectionList)
        )
        if selections:
            return selections[0]
    return app.query_one("#onboard-body SelectionList", SelectionList)


async def start_clone(app, pilot, *, connect_github: bool) -> None:
    """Navigate the wizard to its clone visibility or public URL screen."""
    if connect_github:
        await connect_github_app(app, pilot)
    else:
        await skip_machine_github(pilot)
    await pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    expected_body = (
        "Is the repo public or private?"
        if connect_github
        else onboard_github_copy.CLONE_FROM_GITHUB_SUBTITLE
    )
    text = await wait_for_body_text(app, pilot, expected_body)
    assert expected_body in text
