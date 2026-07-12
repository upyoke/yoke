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

from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import project_clone_support as clone  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    complete_board_art,
    make_app,
    type_text,
)
from runtime.api.cli.onboard_wizard_github_app_test_support import (  # noqa: E402
    connect_github_app,
    select_connected_repository,
)
from runtime.api.cli.onboard_wizard_clone_test_support import (  # noqa: E402
    configure_clone_flow,
    pick_mode,
)


@pytest.fixture(autouse=True)
def _configure_clone_flow(monkeypatch):
    configure_clone_flow(monkeypatch)


async def _to_clone_outcome(app, pilot) -> None:
    await connect_github_app(app, pilot)
    await pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    await pilot.press("enter")  # visibility: Public (default) -> paste-URL input
    await type_text(pilot, "git@github.com:acme/widgets.git")  # remote url
    await pilot.press("enter")  # remote -> clone-folder input (default ~/code/widgets)
    await pilot.press("enter")  # accept default folder -> clone-outcome screen


def test_clone_it_keeps_origin_on_source() -> None:
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _to_clone_outcome(app, pilot)
            await pilot.press("enter")  # "Clone it" (default, first row)
            await pilot.press("enter")  # slug placeholder
            await pilot.press("enter")  # name placeholder
            # just-clone records the source repo and routes through project
            # github auth (origin stays the source); reuse-machine then finish.
            # No "default branch" prompt for a clone — it's detected from the
            # source at the URL step, so the name input lands straight on prefix.
            await pilot.press("enter")  # prefix
            await select_connected_repository(app, pilot)
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
            await _to_clone_outcome(app, pilot)
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
            await select_connected_repository(app, pilot)
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
    assert plan.fallback_token is None
    assert plan.use_machine_github is True
    publish = plan.publish
    assert publish is not None
    assert publish.owner == "octocat"
    assert publish.private is True


def test_duplicate_public_visibility_sets_public_publish() -> None:
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _to_clone_outcome(app, pilot)
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
            await select_connected_repository(app, pilot)
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


def test_fork_builds_clone_plan_with_app_access() -> None:
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _to_clone_outcome(app, pilot)
            await pilot.press("down")   # move to "Duplicate it"
            await pilot.press("down")   # move to "Fork it"
            await pilot.press("enter")  # outcome: Fork it
            await pilot.press("enter")  # slug
            await pilot.press("enter")  # name
            # clone skips the default-branch prompt
            await pilot.press("enter")  # prefix
            await select_connected_repository(app, pilot)
            await complete_board_art(pilot)  # board art -> Finish
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    plan = applied["project_clone"]
    assert plan is not None
    assert plan.outcome == clone.CLONE_OUTCOME_FORK
    assert plan.fallback_token is None
    assert plan.use_machine_github is True
    assert plan.publish is None
    # Fork does not run the keep-upstream screen; the default stays True but is
    # ignored by the fork outcome (it always tracks the source as upstream).
    assert applied["project_publish"] is None


def test_duplicate_without_app_connection_falls_back_to_just_clone(monkeypatch) -> None:
    # No App connection: the push probe has nothing to probe and the clone-outcome
    # screen shows the read-only variant; duplicate then degrades to just-clone at
    # name time because there is no App connection to create the new repo with.
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")   # machine github: Skip for now
            await pilot.press("enter")  # continue without GitHub
            await pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await type_text(pilot, "git@github.com:acme/widgets.git")  # remote first
            await pilot.press("enter")  # remote -> clone-folder input
            await pilot.press("enter")  # accept default folder -> clone-outcome
            await pilot.press("down")   # "Duplicate it"
            await pilot.press("enter")
            await pilot.press("enter")  # new-repo visibility: Private (default)
            await pilot.press("enter")  # slug (no keep-upstream screen)
            await pilot.press("enter")  # name -> no App, falls back to just-clone
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
    # Without a connected App there is nothing to create the new repo with, so
    # the wizard degrades to a plain clone rather than stranding the user.
    assert plan.outcome == clone.CLONE_OUTCOME_JUST_CLONE
    assert plan.publish is None
