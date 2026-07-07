"""Wizard coverage for the "Also publish to GitHub?" follow-up.

The publish prompt is shown for the existing-folder (local-checkout) and
create-new paths and routes a Yes through the owner picker and repo-name input.
With a connected machine token Yes goes straight to the owner picker; without
one Yes collects a PAT first and reuses it as the publish credential, so the
offer is never silently suppressed. The owner list is fetched behind a seam
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


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


@pytest.fixture(autouse=True)
def _stub_owners(monkeypatch):
    monkeypatch.setattr(
        onboard_wizard_flow, "fetch_repo_owners",
        lambda api_url, token: [
            github_publish.RepoOwner("octocat", "user"),
            github_publish.RepoOwner("acme-inc", "organization"),
        ],
    )


async def _connect_machine_pat(pilot) -> None:
    await advance_past_path(pilot)
    await pilot.press("enter")  # machine github: Connect a token (PAT) (default)
    await type_text(pilot, "ghp_machinepat")
    await pilot.press("enter")
    await pilot.press("enter")  # GitHub verification success: Continue


async def _pick_mode(pilot, value: str) -> None:
    index = next(i for i, r in enumerate(steps.MODE_ROWS) if r.value == value)
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")


def test_local_checkout_offers_publish_and_creates_request(monkeypatch) -> None:
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _connect_machine_pat(pilot)
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
            # reuse-machine project github auth then finish
            reuse_index = next(
                i for i, r in enumerate(steps.PROJECT_GITHUB_ROWS)
                if r.value == "reuse-machine"
            )
            for _ in range(reuse_index):
                await pilot.press("down")
            await pilot.press("enter")
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
            await _connect_machine_pat(pilot)
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
            await _connect_machine_pat(pilot)
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
            await pilot.press("enter")  # project github: reuse machine (default)
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
            await _connect_machine_pat(pilot)
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


def test_no_machine_token_publish_no_keeps_it_local() -> None:
    """Without a machine token the publish prompt is still shown; No stays local."""
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")   # machine github: Skip for now
            await pilot.press("enter")  # (no token)
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
    assert applied["machine_github_token"] is None


def test_no_machine_token_publish_yes_prompts_for_pat_and_publishes() -> None:
    """Without a machine token, Yes collects a PAT first, then publishes with it.

    The prompted PAT is reused as the publish credential: the owner picker can
    list owners and the assembled PublishRequest carries the token, so create-new
    always has a way to set up GitHub even when the machine step was skipped.
    """
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")   # machine github: Skip for now
            await pilot.press("enter")  # (no token)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CREATE_REPO)
            await type_text(pilot, "/home/code/widget")  # new folder path
            await pilot.press("enter")
            await pilot.press("enter")  # slug placeholder -> widget
            await pilot.press("enter")  # name placeholder
            await pilot.press("enter")  # publish: Yes (preselected)
            await type_text(pilot, "ghp_publishpat")  # PAT prompt (no machine token)
            await pilot.press("enter")
            await pilot.press("enter")  # owner picker: octocat (first row)
            await pilot.press("enter")  # repo name placeholder -> widget
            await pilot.press("enter")  # default branch main
            await pilot.press("enter")  # prefix placeholder
            reuse_index = next(
                i for i, r in enumerate(steps.PROJECT_GITHUB_ROWS)
                if r.value == onboard_wizard_flow.PROJECT_GITHUB_REUSE_MACHINE
            )
            for _ in range(reuse_index):
                await pilot.press("down")
            await pilot.press("enter")  # project github: reuse the prompted PAT
            await complete_board_art(pilot)  # board art -> Finish
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    # The prompted PAT is held on the machine-token field (used to publish, but
    # machine_github_choice stays skip, so it is not saved as a connection).
    assert applied["machine_github_token"] == "ghp_publishpat"
    assert applied["machine_github_choice"] == "skip"
    assert applied["project_github_repo"] == "octocat/widget"
    publish = applied["project_publish"]
    assert publish is not None
    assert publish.owner == "octocat"
    assert publish.name == "widget"
    assert publish.token == "ghp_publishpat"
    assert publish.private is True
