"""Wizard coverage for the clone-outcome flow (clone / duplicate / fork).

The clone-URL input is followed by the clone-outcome screen whose default is
"Clone it" (first row); "Duplicate it" adds only the new-repo visibility step
(public / private) before reusing the publish owner-picker + repo-name screens —
there is no keep-upstream follow-up, and the source is always kept as a pull-only
``upstream`` remote. The push-access probe is stubbed per scenario so the
writable / read-only row set is deterministic; ``build_report`` is spied at the
wizard boundary and the owner list is stubbed, so no scenario hits GitHub or git.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Input, Static  # noqa: E402

from yoke_cli.config import github_publish  # noqa: E402
from yoke_cli.config import existing_project_lookup  # noqa: E402
from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_flow  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_clone as clone_flow  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config import project_clone_support as clone  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    complete_board_art,
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
    # The clone path no longer prompts for the default branch — it detects the
    # source's branch at the URL step. Stub the probe so flow scenarios stay
    # offline and the detected branch is a fixed `main`.
    stub_source_branch(monkeypatch, "main")


@pytest.fixture(autouse=True)
def _stub_owners(monkeypatch):
    monkeypatch.setattr(
        onboard_wizard_flow, "fetch_repo_owners",
        lambda api_url, token: [
            github_publish.RepoOwner("octocat", "user"),
            github_publish.RepoOwner("acme-inc", "organization"),
        ],
    )


@pytest.fixture(autouse=True)
def _stub_push_access(monkeypatch):
    """Default the source-push probe to read-only so the fork row is offered.

    Read-only is the safe default the screen renders when the probe is unknown;
    it keeps "Fork it" in the row set for the github source these scenarios use.
    Writable-variant scenarios override this seam to True directly.
    """
    monkeypatch.setattr(
        clone_flow.CloneFlow, "_source_push_access", lambda self: None
    )


async def _connect_machine_pat(pilot) -> None:
    await advance_past_path(pilot)
    await pilot.press("enter")  # machine github: Connect a token (GitHub App user token) (default)
    await type_text(pilot, "ghu_machine_token")
    await pilot.press("enter")
    await pilot.press("enter")  # GitHub verification success: Continue


async def _pick_mode(pilot, value: str) -> None:
    index = next(i for i, r in enumerate(steps.MODE_ROWS) if r.value == value)
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")


async def _to_clone_outcome(pilot) -> None:
    await _connect_machine_pat(pilot)
    await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    await pilot.press("enter")  # visibility: Public (default) -> paste-URL input
    await type_text(pilot, "git@github.com:acme/widgets.git")  # remote url
    await pilot.press("enter")  # remote -> clone-folder input (default ~/code/widgets)
    await pilot.press("enter")  # accept default folder -> clone-outcome screen


def test_clone_it_keeps_origin_on_source() -> None:
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _to_clone_outcome(pilot)
            await pilot.press("enter")  # "Clone it" (default, first row)
            await pilot.press("enter")  # slug placeholder
            await pilot.press("enter")  # name placeholder
            # just-clone records the source repo and routes through project
            # github auth (origin stays the source); reuse-machine then finish.
            reuse_index = next(
                i for i, r in enumerate(steps.PROJECT_GITHUB_ROWS)
                if r.value == "reuse-machine"
            )
            # No "default branch" prompt for a clone — it's detected from the
            # source at the URL step, so the name input lands straight on prefix.
            await pilot.press("enter")  # prefix
            for _ in range(reuse_index):
                await pilot.press("down")
            await pilot.press("enter")  # project github reuse-machine
            await complete_board_art(pilot)  # board art -> Finish
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    plan = applied["project_clone"]
    assert plan is not None
    assert plan.outcome == clone.CLONE_OUTCOME_JUST_CLONE
    assert applied["project_publish"] is None
    # The detected source branch is recorded, not prompted for.
    assert applied["project_default_branch"] == "main"


def test_duplicate_private_always_keeps_upstream_skips_upstream_screen() -> None:
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _to_clone_outcome(pilot)
            await pilot.press("down")   # move to "Duplicate it"
            await pilot.press("enter")
            await pilot.press("enter")  # new-repo visibility: Private (default)
            await pilot.pause()
            # Visibility lands directly on the name input — there is NO
            # keep-upstream selection screen in between.
            assert app.query_one("#onboard-input", Input) is not None
            title = next(
                str(w.render()) for w in app.query(".onboard-title").results(Static)
            )
            assert title == "Name your project."
            await pilot.press("enter")  # slug placeholder -> widgets
            await pilot.press("enter")  # name placeholder
            await pilot.press("enter")  # owner picker: octocat (first)
            await pilot.press("enter")  # repo name placeholder -> widgets
            # Clone path skips the default-branch prompt (detected at URL step).
            await pilot.press("enter")  # prefix
            reuse_index = next(
                i for i, r in enumerate(steps.PROJECT_GITHUB_ROWS)
                if r.value == "reuse-machine"
            )
            for _ in range(reuse_index):
                await pilot.press("down")
            await pilot.press("enter")  # project github reuse-machine
            await complete_board_art(pilot)  # board art -> Finish
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    plan = applied["project_clone"]
    assert plan is not None
    assert plan.outcome == clone.CLONE_OUTCOME_MAKE_IT_MINE
    # "Duplicate it" always keeps the source as a pull-only upstream — that is
    # what lets a private copy pull from a public original.
    assert plan.keep_upstream is True
    assert plan.fallback_token == "ghu_machine_token"
    publish = plan.publish
    assert publish is not None
    assert publish.owner == "octocat"
    assert publish.private is True


def test_duplicate_public_visibility_sets_public_publish() -> None:
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _to_clone_outcome(pilot)
            await pilot.press("down")   # "Duplicate it"
            await pilot.press("enter")
            await pilot.press("down")   # new-repo visibility: move to Public
            await pilot.press("enter")  # -> name input (no keep-upstream screen)
            await pilot.press("enter")  # slug
            await pilot.press("enter")  # name
            await pilot.press("enter")  # owner picker: octocat
            await pilot.press("enter")  # repo name
            # clone skips the default-branch prompt
            await pilot.press("enter")  # prefix
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
    plan = applied["project_clone"]
    assert plan is not None
    assert plan.outcome == clone.CLONE_OUTCOME_MAKE_IT_MINE
    # A public duplicate still keeps the source as upstream — visibility of the
    # new repo is independent of the always-kept pull-only upstream link.
    assert plan.keep_upstream is True
    publish = plan.publish
    assert publish is not None
    assert publish.private is False


def test_fork_builds_clone_plan_with_token() -> None:
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _to_clone_outcome(pilot)
            await pilot.press("down")   # move to "Duplicate it"
            await pilot.press("down")   # move to "Fork it"
            await pilot.press("enter")  # outcome: Fork it
            await pilot.press("enter")  # slug
            await pilot.press("enter")  # name
            # clone skips the default-branch prompt
            await pilot.press("enter")  # prefix
            reuse_index = next(
                i for i, r in enumerate(steps.PROJECT_GITHUB_ROWS)
                if r.value == "reuse-machine"
            )
            for _ in range(reuse_index):
                await pilot.press("down")
            await pilot.press("enter")  # project github reuse-machine
            await complete_board_art(pilot)  # board art -> Finish
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    plan = applied["project_clone"]
    assert plan is not None
    assert plan.outcome == clone.CLONE_OUTCOME_FORK
    assert plan.fallback_token == "ghu_machine_token"
    assert plan.publish is None
    # Fork does not run the keep-upstream screen; the default stays True but is
    # ignored by the fork outcome (it always tracks the source as upstream).
    assert applied["project_publish"] is None


def test_clone_existing_yoke_project_uses_project_id_and_skips_setup(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        existing_project_lookup,
        "find_by_github_repo",
        lambda **_: existing_project_lookup.ExistingProject(
            id=37,
            slug="buzz",
            name="Buzz",
            github_repo="example-org/buzz",
            default_branch="main",
            public_item_prefix="BUZZ",
        ),
    )
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _connect_machine_pat(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await pilot.press("enter")  # visibility: Public
            await type_text(pilot, "git@github.com:example-org/buzz.git")
            await pilot.press("enter")  # remote -> clone-folder input
            await pilot.press("enter")  # folder -> existing project ready
            await pilot.pause()
            title = next(
                str(w.render()) for w in app.query(".onboard-title").results(Static)
            )
            body = _body_text(app)
            assert title == "Existing Yoke project found."
            assert (
                "The Yoke core database already has a project for this GitHub repo."
                in body
            )
            assert "Yoke core database: matched GitHub repo example-org/buzz." in body
            assert (
                "Local machine: no existing Yoke project metadata was used."
                in body
            )
            assert "Clone target: ~/code/buzz" in body
            assert "Using existing checkout:" not in body
            await pilot.press("enter")  # continue -> board art
            await complete_board_art(pilot)
            await pilot.press("enter")  # apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["existing_project_id"] == 37
    assert applied["project_slug"] == "buzz"
    assert applied["project_name"] == "Buzz"
    assert applied["project_github_repo"] == "example-org/buzz"
    assert applied["project_public_item_prefix"] == "BUZZ"
    assert applied["project_github_adoption"] == "skip"
    assert len(app.result.board_art_variants) == 1
    plan = applied["project_clone"]
    assert plan is not None
    assert plan.outcome == clone.CLONE_OUTCOME_JUST_CLONE
    assert plan.fallback_token == "ghu_machine_token"


def _body_text(app) -> str:
    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


def test_clone_existing_yoke_project_access_error_blocks_setup(monkeypatch) -> None:
    def _deny(**_kwargs):
        raise existing_project_lookup.ExistingProjectAccessError(
            "this Yoke token cannot access project 37"
        )

    monkeypatch.setattr(
        existing_project_lookup,
        "find_by_github_repo",
        _deny,
    )
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _connect_machine_pat(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await pilot.press("enter")  # visibility: Public
            await type_text(pilot, "git@github.com:example-org/buzz.git")
            await pilot.press("enter")
            await pilot.pause()
            title = next(
                str(w.render())
                for w in app.query(".onboard-title-error").results(Static)
            )
            assert title == "✗ Can't use that Yoke project."

    asyncio.run(scenario())

    assert spy.applied is None
    assert app.result.existing_project_id is None


def test_duplicate_without_token_falls_back_to_just_clone(monkeypatch) -> None:
    # No machine token: the push probe has nothing to probe and the clone-outcome
    # screen shows the read-only variant; duplicate then degrades to just-clone at
    # name time because there is no token to create the new repo with.
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")   # machine github: Skip for now
            await pilot.press("enter")  # (no token)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await type_text(pilot, "git@github.com:acme/widgets.git")  # remote first
            await pilot.press("enter")  # remote -> clone-folder input
            await pilot.press("enter")  # accept default folder -> clone-outcome
            await pilot.press("down")   # "Duplicate it"
            await pilot.press("enter")
            await pilot.press("enter")  # new-repo visibility: Private (default)
            await pilot.press("enter")  # slug (no keep-upstream screen)
            await pilot.press("enter")  # name -> no token, falls back to just-clone
            # clone skips the default-branch prompt
            await pilot.press("enter")  # prefix
            await complete_board_art(pilot)  # board art -> Finish
            await pilot.press("enter")  # finish: apply (no project github step)
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    plan = applied["project_clone"]
    assert plan is not None
    # Without a connected token there is nothing to create the new repo with, so
    # the wizard degrades to a plain clone rather than stranding the user.
    assert plan.outcome == clone.CLONE_OUTCOME_JUST_CLONE
    assert plan.publish is None
