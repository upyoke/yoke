"""Wizard coverage for cloning repositories already known to Yoke."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Static  # noqa: E402

from yoke_cli.config import existing_project_lookup  # noqa: E402
from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import project_clone_support as clone  # noqa: E402

from runtime.api.cli.onboard_wizard_clone_test_support import (  # noqa: E402
    configure_clone_flow,
    pick_mode,
)
from runtime.api.cli.onboard_wizard_github_app_test_support import (  # noqa: E402
    connect_github_app,
    select_connected_repository,
)
from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    complete_board_art,
    make_app,
    type_text,
)


@pytest.fixture(autouse=True)
def _configure_clone_flow(monkeypatch):
    configure_clone_flow(monkeypatch)


def _body_text(app) -> str:
    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


def test_clone_existing_yoke_project_offers_binding_upgrade(
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
            await connect_github_app(app, pilot)
            await pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
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
            assert "Local machine: no existing Yoke project metadata was used." in body
            assert "Clone target: ~/code/buzz" in body
            assert "Using existing checkout:" not in body
            await pilot.press("enter")  # continue -> project GitHub choice
            await select_connected_repository(app, pilot)
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
    assert applied["project_github_adoption"] == "app-binding"
    assert len(app.result.board_art_variants) == 1
    plan = applied["project_clone"]
    assert plan is not None
    assert plan.outcome == clone.CLONE_OUTCOME_JUST_CLONE
    assert plan.fallback_token is None
    assert plan.use_machine_github is True


def test_clone_existing_yoke_project_access_error_blocks_setup(monkeypatch) -> None:
    def _deny(**_kwargs):
        raise existing_project_lookup.ExistingProjectAccessError(
            "this Yoke token cannot access project 37"
        )

    monkeypatch.setattr(existing_project_lookup, "find_by_github_repo", _deny)
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await connect_github_app(app, pilot)
            await pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await pilot.press("enter")  # visibility: Public
            await type_text(pilot, "git@github.com:example-org/buzz.git")
            await pilot.press("enter")
            await pilot.pause()
            title = next(
                str(w.render())
                for w in app.query(".onboard-title-error").results(Static)
            )
            assert title == "✗ Can't use that Yoke project."
            error_depth = len(app._history)
            await pilot.press("enter")  # Try again
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "Can't use that Yoke project." in _body_text(app)
            assert len(app._history) == error_depth
            await pilot.press("down")  # Back
            await pilot.press("enter")
            await pilot.pause()
            assert "Set up a project." in _body_text(app)
            assert len(app._history) < error_depth
            await pilot.press("escape")
            await pilot.pause()
            assert "Can't use that Yoke project." not in _body_text(app)

    asyncio.run(scenario())

    assert spy.applied is None
    assert app.result.existing_project_id is None
