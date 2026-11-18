"""The publish prompt respects the earlier GitHub connection choice."""

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_machine_github, onboard_project  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp  # noqa: E402
from yoke_cli.config.onboard_wizard_project_screens import PUBLISH_YES  # noqa: E402

MODES = pytest.mark.parametrize(
    "mode",
    [
        onboard_project.PROJECT_MODE_CREATE_REPO,
        onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
    ],
)
DETAILS = {"slug": "my-project", "name": "My Project", "prefix": "MP"}


def _app(mode: str, checkout: str, *, connected: bool) -> OnboardWizardApp:
    app = OnboardWizardApp(defaults=WizardDefaults(), apply_report=lambda _: {})
    app._start_front = lambda: None
    app.result.project_mode = mode
    app.result.project_checkout = checkout
    app.result.machine_github_choice = (
        onboard_machine_github.CHOICE_CONNECT
        if connected
        else onboard_machine_github.CHOICE_SKIP
    )
    app.result.machine_github_verification = (
        {"ok": True, "ready": True} if connected else None
    )
    return app


@MODES
def test_github_skipped_never_offers_publish(mode, tmp_path) -> None:
    async def scenario() -> None:
        app = _app(mode, str(tmp_path), connected=False)
        shown: list[str] = []
        continued: list[str] = []
        goto = app._goto

        def record(view) -> None:
            shown.append(view.prompt.key)
            goto(view)

        app._goto = record
        app._after_repo = continued.append

        async with app.run_test() as pilot:
            app._after_project_details(DETAILS)
            await pilot.pause()
            assert "project.publish" not in shown
            assert continued == [""]
            assert app.result.project_publish_to_github is False

    asyncio.run(scenario())


@MODES
def test_github_connected_offers_publish_with_yes_selected(mode, tmp_path) -> None:
    async def scenario() -> None:
        app = _app(mode, str(tmp_path), connected=True)
        selected: list[str] = []
        app._on_publish_choice = selected.append

        async with app.run_test() as pilot:
            app._after_project_details(DETAILS)
            await pilot.pause()
            assert app._history[-1].prompt.key == "project.publish"
            await pilot.press("enter")
            assert selected == [PUBLISH_YES]

    asyncio.run(scenario())
