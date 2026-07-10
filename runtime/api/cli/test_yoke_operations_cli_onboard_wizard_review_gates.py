"""Live-wizard coverage for the publish-GitHub App user token and Review pre-flight Apply gates.

Companion to the inline-validation suite: these two gates fire later in the flow
(at the publish-only GitHub auth prompt and on the Review screen) and withhold the
forward action until the problem clears, rather than failing at Apply. Driven
through the real ``OnboardWizardApp`` pilot reading the live DOM.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Static  # noqa: E402

from yoke_cli.config import onboard_project  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    complete_board_art,
    make_app,
    stub_path_doctor,
    type_text,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


@pytest.fixture(autouse=True)
def _stub_owners(monkeypatch):
    from yoke_cli.config import github_publish
    from yoke_cli.config import onboard_wizard_flow

    monkeypatch.setattr(
        onboard_wizard_flow, "fetch_repo_owners",
        lambda api_url, token: [github_publish.RepoOwner("octocat", "user")],
    )


async def _pick_mode(pilot, value: str) -> None:
    from yoke_cli.config import onboard_wizard_steps as steps

    index = next(i for i, r in enumerate(steps.MODE_ROWS) if r.value == value)
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")


async def _skip_machine_github(pilot) -> None:
    await advance_past_path(pilot)
    await pilot.press("down")   # machine github: Skip for now
    await pilot.press("enter")


def _body_text(app) -> str:
    return " ".join(
        str(w.render()) for w in app.query("#onboard-body Static").results(Static)
    )


def test_review_preflight_blocks_apply_until_clear(monkeypatch) -> None:
    """A pre-flight problem on the Review screen withholds Apply.

    The Review screen shows the problem and the only forward row is "Back to fix
    that"; pressing it (the position Apply would occupy) does NOT apply.
    """
    from yoke_cli.config.onboard_wizard_flow import WizardFlow
    from yoke_cli.config.onboard_preflight import PreflightResult

    # Force one pre-flight problem so the Review screen renders the blocked rows.
    monkeypatch.setattr(
        WizardFlow, "_review_preflight",
        lambda self: PreflightResult(
            problems=["That folder already has files — pick an empty or new path."],
            notes=[],
        ),
    )

    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
            await type_text(pilot, "/home/code/widget")
            await pilot.press("enter")
            await pilot.press("enter")  # slug
            await pilot.press("enter")  # name
            await pilot.press("down")   # publish: No
            await pilot.press("enter")
            await pilot.press("enter")  # default branch main
            await pilot.press("enter")  # prefix
            await complete_board_art(pilot)  # board art -> Review (blocked)
            await pilot.pause()
            body = _body_text(app)
            assert "to fix before applying" in body.lower()
            assert "already has files" in body.lower()
            # The first (default) row is "Back to fix that", not "Apply" — pressing
            # Enter steps back instead of applying.
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()

    asyncio.run(scenario())

    # Nothing was applied — the pre-flight gate held.
    assert spy.applied is None
