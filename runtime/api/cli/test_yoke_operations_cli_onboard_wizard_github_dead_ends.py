"""Regression coverage for the project-GitHub picker Apply dead-ends.

These bugs all rendered a green write-plan at apply=False but raised at
apply=True with no in-wizard recovery. The picker offered connected-repo choices
without a usable GitHub App authorization, and back-navigation left stale project
GitHub state after the user re-chose backlog-only or declined publish. The fixes
gate the connected-repo row by machine GitHub authorization and clear stale
binding state.

The suite drives the real ``OnboardWizardApp`` routing through the pilot to the
buggy state, then asserts the picker rows and the collected ``WizardResult`` so
the cleaned state no longer trips ``github_adoption_report`` at apply=True.
``github_adoption_report`` is the exact function that raised in both back-nav
dead-ends, so re-running it on the collected fields (network-free) proves the
dead-end is gone without driving the full machine-write apply path.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_cli.config import github_publish  # noqa: E402
from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_flow  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config.onboard_wizard import PROJECT_GITHUB_REUSE_MACHINE  # noqa: E402
from yoke_cli.config.project_github_adoption import (  # noqa: E402
    GITHUB_ADOPTION_APP_BINDING,
    GITHUB_ADOPTION_BACKLOG_ONLY,
    github_adoption_report,
)
from yoke_cli.config.onboard_wizard_widgets import SelectionList  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
    stub_source_branch,
    type_text,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


@pytest.fixture(autouse=True)
def _stub_source_branch(monkeypatch):
    stub_source_branch(monkeypatch, "main")


@pytest.fixture(autouse=True)
def _stub_owners(monkeypatch):
    # The create=True publish path proceeds to the owner picker, which fetches
    # owners over the network; stub it so no scenario hits GitHub.
    monkeypatch.setattr(
        onboard_wizard_flow, "fetch_repo_owners",
        lambda api_url, token: [github_publish.RepoOwner("octocat", "user")],
    )


async def _pick_mode(pilot, value: str) -> None:
    index = next(i for i, r in enumerate(steps.MODE_ROWS) if r.value == value)
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")


def _adoption_call(result) -> dict:
    """Re-run the apply-time adoption gate on the collected fields.

    Returns the report when the gate accepts the state; raises the same
    ProjectGithubAdoptionError the wizard's apply path would surface otherwise.
    """
    return github_adoption_report(
        choice=result.project_github_adoption,
        github_repo=result.project_github_repo,
        token_value=result.project_github_token,
        token_import_method="direct" if result.project_github_token else None,
        apply=True,
    )


def _row_values(app) -> list[str]:
    selection = app.query_one("#onboard-body SelectionList", SelectionList)
    return [row.value for row in selection.rows]


# --------------------------------------------------------------------------- #
# Bug A — reuse-machine offered with no machine token
# --------------------------------------------------------------------------- #


def test_no_machine_token_drops_reuse_machine_row() -> None:
    """The picker omits reuse-machine when no machine token was connected."""
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")   # machine github: Skip for now (no GitHub App user token)
            await pilot.press("enter")
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await type_text(pilot, "https://github.com/acme/widgets.git")  # remote first
            await pilot.press("enter")  # remote -> clone-folder input
            await pilot.press("enter")  # accept default folder -> clone-outcome
            await pilot.press("enter")  # "Clone it" (default, first row)
            await pilot.press("enter")  # slug placeholder
            await pilot.press("enter")  # name placeholder
            # clone skips the default-branch prompt (detected at URL step)
            await pilot.press("enter")  # prefix -> project github picker
            await pilot.pause()
            values = _row_values(app)
            assert PROJECT_GITHUB_REUSE_MACHINE not in values
            assert values == [r.value for r in steps.PROJECT_GITHUB_ROWS_NO_MACHINE]

    asyncio.run(scenario())


def test_forced_reuse_machine_without_token_degrades_to_skip() -> None:
    """Defense in depth: a reuse-machine choice with no token becomes skip.

    Driven at the handler inside a running app so a forced reuse-machine value
    (e.g. a future row regression) still cannot produce app-binding + no repo.
    """
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test():
            app.result.machine_github_token = None
            app.result.project_github_repo = "acme/widgets"
            app.result.project_github_token = None
            app._on_project_github(PROJECT_GITHUB_REUSE_MACHINE)

    asyncio.run(scenario())

    assert app.result.project_github_adoption == "skip"
    assert app.result.project_github_token is None
    # The apply-time adoption gate accepts the degraded skip state.
    assert _adoption_call(app.result)["choice"] == GITHUB_ADOPTION_BACKLOG_ONLY


# --------------------------------------------------------------------------- #
# Bug D — back-nav leaves a stale project token / adoption
# --------------------------------------------------------------------------- #


def test_skip_after_app_binding_clears_stale_project_token() -> None:
    """Re-selecting backlog-only clears stale project GitHub credentials.

    Carrying a token into a backlog-only adoption is no longer supported and
    would raise at apply.
    """
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test():
            app.result.machine_github_token = "ghu_machine_token"
            app.result.project_github_repo = "acme/widgets"
            # A prior visit left App-binding state plus a stale token.
            app.result.project_github_adoption = GITHUB_ADOPTION_APP_BINDING
            app.result.project_github_token = "ghs_project_token"
            app._on_project_github("skip")

    asyncio.run(scenario())

    assert app.result.project_github_token is None
    assert app.result.project_github_adoption == "skip"
    # The cleaned skip state no longer trips the apply-time gate.
    assert _adoption_call(app.result)["choice"] == GITHUB_ADOPTION_BACKLOG_ONLY


def test_declined_publish_clears_app_binding_adoption() -> None:
    """Clearing the repo (declined publish) resets stale App-binding adoption.

    Leaving adoption='app-binding' with no repo raised "GitHub
    adoption requires --github-repo OWNER/REPO" at apply.
    """
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test():
            app.result.machine_github_token = "ghu_machine_token"
            # Prior connected-repo visit set adoption, then the user
            # back-navigated to the publish prompt and declined.
            app.result.project_github_repo = "acme/widgets"
            app.result.project_github_adoption = GITHUB_ADOPTION_APP_BINDING
            app.result.project_github_token = "ghs_project_token"
            app._after_repo("")

    asyncio.run(scenario())

    assert app.result.project_github_repo is None
    assert app.result.project_github_adoption is None
    assert app.result.project_github_token is None
    # With no repo and no adoption/token, the gate normalizes to skip and
    # accepts it instead of raising.
    assert _adoption_call(app.result)["choice"] == GITHUB_ADOPTION_BACKLOG_ONLY
