"""The publish prompt respects the earlier GitHub connection choice."""

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_machine_github, onboard_project  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp  # noqa: E402
from yoke_cli.config.onboard_wizard_project_screens import (  # noqa: E402
    PUBLISH_NO,
    PUBLISH_YES,
)


@pytest.mark.parametrize(
    "mode",
    [
        onboard_project.PROJECT_MODE_CREATE_REPO,
        onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
    ],
)
@pytest.mark.parametrize(
    "connected", [False, True], ids=["github-skipped", "github-connected"]
)
def test_enter_accepts_publish_default(mode, connected, tmp_path) -> None:
    async def scenario() -> None:
        selected: list[str] = []
        app = OnboardWizardApp(defaults=WizardDefaults(), apply_report=lambda _: {})
        app._start_front = lambda: None
        app._on_publish_choice = selected.append
        app.result.project_mode = mode
        app.result.project_checkout = str(tmp_path)
        app.result.machine_github_choice = (
            onboard_machine_github.CHOICE_CONNECT
            if connected
            else onboard_machine_github.CHOICE_SKIP
        )
        app.result.machine_github_verification = (
            {"ok": True, "ready": True} if connected else None
        )

        async with app.run_test() as pilot:
            app._goto_publish_prompt()
            await pilot.pause()
            await pilot.press("enter")
            assert selected == [PUBLISH_YES if connected else PUBLISH_NO]

    asyncio.run(scenario())
