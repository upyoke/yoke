"""Wizard coverage for the "Also publish to GitHub?" follow-up.

The publish prompt is shown for the existing-folder (local-checkout) and
create-new paths and routes a Yes through the owner picker and repo-name input.
With a connected GitHub App, Yes goes straight to the owner picker. Without
one, the user can keep the project local; no credential is collected by the
wizard. The owner list is fetched behind a seam
patched here so no scenario hits GitHub; ``build_report`` is spied at the
wizard boundary.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("textual")

from yoke_cli.config import github_publish  # noqa: E402
from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_flow  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    complete_board_art,
    make_app,
    stub_path_doctor,
    type_text,
)
from runtime.api.cli.onboard_wizard_github_app_test_support import (  # noqa: E402
    connect_github_app,
    select_connected_repository,
    stub_github_app_access,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


@pytest.fixture(autouse=True)
def _stub_github_app(monkeypatch, _stub_path_doctor):
    monkeypatch.setattr(
        onboard_wizard_flow, "fetch_repo_owners",
        lambda api_url, token: [
            github_publish.RepoOwner("octocat", "user"),
            github_publish.RepoOwner("acme-inc", "organization"),
        ],
    )
    stub_github_app_access(
        monkeypatch,
        owners=("octocat", "acme-inc"),
        repositories=("octocat/widget", "acme-inc/thing"),
        user_access_token="short-lived-publish-access",
    )


async def _pick_mode(pilot, value: str) -> None:
    index = next(i for i, r in enumerate(steps.MODE_ROWS) if r.value == value)
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")


def test_local_checkout_offers_publish_and_creates_request(monkeypatch) -> None:
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await connect_github_app(app, pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
            await type_text(pilot, "/home/code/widget")  # checkout
            await pilot.press("enter")
            await pilot.press("enter")  # slug placeholder -> widget
            await pilot.press("enter")  # name placeholder
            await pilot.press("enter")  # publish: Yes (preselected)
            await pilot.press("enter")  # owner picker: octocat (first row)
            await pilot.press("enter")  # repo name placeholder -> widget
            await pilot.press("enter")  # default branch main
            await pilot.press("enter")  # prefix placeholder
            await select_connected_repository(app, pilot)
            await complete_board_art(pilot)  # board art -> Finish
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["project_mode"] == onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
    assert applied["project_github_repo"] == "octocat/widget"
    publish = applied["project_publish"]
    assert publish is not None
    assert publish.owner == "octocat"
    assert publish.name == "widget"
    assert publish.private is True


def test_publish_no_keeps_it_local(monkeypatch) -> None:
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await connect_github_app(app, pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
            await type_text(pilot, "/home/code/widget")
            await pilot.press("enter")
            await pilot.press("enter")  # slug
            await pilot.press("enter")  # name
            await pilot.press("down")   # publish: move to No
            await pilot.press("enter")  # publish: No — keep local
            await pilot.press("enter")  # default branch main
            await pilot.press("enter")  # prefix placeholder
            await complete_board_art(pilot)  # board art -> Finish
            await pilot.press("enter")  # finish: apply (no project github step)
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["project_publish"] is None
    assert not applied["project_github_repo"]


def test_owner_picker_routes_org_with_user_login() -> None:
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await connect_github_app(app, pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CREATE_REPO)
            await type_text(pilot, "/home/code/widget")
            await pilot.press("enter")
            await pilot.press("enter")  # slug
            await pilot.press("enter")  # name
            await pilot.press("enter")  # publish: Yes
            await pilot.press("down")   # owner picker: move to acme-inc
            await pilot.press("enter")  # pick acme-inc (org)
            await type_text(pilot, "thing")  # repo name
            await pilot.press("enter")
            await pilot.press("enter")  # default branch main
            await pilot.press("enter")  # prefix placeholder
            await select_connected_repository(app, pilot)
            await complete_board_art(pilot)  # board art -> Finish
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    publish = applied["project_publish"]
    assert publish is not None
    assert publish.owner == "acme-inc"
    assert publish.name == "thing"
    # The user-vs-org create endpoint keys on the authenticated user login,
    # which stays octocat even when an org owner is chosen.
    assert publish.user_login == "octocat"
    assert applied["project_github_repo"] == "acme-inc/thing"


def test_remote_already_present_auto_skips_publish(tmp_path: Path) -> None:
    checkout = tmp_path / "already-remote"
    checkout.mkdir()
    subprocess.run(["git", "init", str(checkout)], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:owner/repo.git"],
        cwd=checkout, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await connect_github_app(app, pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
            await type_text(pilot, str(checkout))
            await pilot.press("enter")
            await pilot.press("enter")  # slug
            await pilot.press("enter")  # name -> publish prompt auto-skipped
            await pilot.press("enter")  # default branch main
            await pilot.press("enter")  # prefix placeholder
            await complete_board_art(pilot)  # board art -> Finish
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["project_publish"] is None


def test_no_app_connection_publish_no_keeps_it_local() -> None:
    """Without an App connection the publish prompt is still shown; No stays local."""
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")   # machine github: Skip for now
            await pilot.press("enter")  # continue without GitHub
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
            await type_text(pilot, "/home/code/widget")
            await pilot.press("enter")
            await pilot.press("enter")  # slug
            await pilot.press("enter")  # name -> publish prompt IS shown now
            await pilot.press("down")   # publish: move to No
            await pilot.press("enter")  # publish: No — keep local
            await pilot.press("enter")  # default branch main
            await pilot.press("enter")  # prefix placeholder
            await complete_board_art(pilot)  # board art -> Finish
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["project_publish"] is None
    assert "machine_github_token" not in applied
