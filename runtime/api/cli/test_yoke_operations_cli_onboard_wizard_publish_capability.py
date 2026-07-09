"""Coverage for the publish-ability guard and publish-only GitHub auth staleness.

The wizard refuses the create+push unless the connected token's real publish-
ability is a confirmed True (create AND push-to-a-new-repo): a scope-bearing token with
no repo scope (can_publish=False) and a select-repositories repository-scoped GitHub App user token
(can create, can't push, can_publish=False) both route to the block screen rather
than orphan an empty repo; an "all repositories" repository-scoped token (can_publish
True) and a scope-bearing repo GitHub App user token both proceed to the owner picker. With no
machine token the guard does not block — the user pastes a publish-only GitHub auth next,
and declining publish afterward drops that GitHub App user token while leaving a genuine machine
connection intact.

The suite drives the real ``OnboardWizardApp`` handlers and reads the rendered
body while the app is still live. The owner list is stubbed so no scenario hits
GitHub.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_cli.config import github_publish  # noqa: E402
from yoke_cli.config import onboard_wizard_flow  # noqa: E402
from yoke_cli.config import onboard_wizard_project_screens as screens  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    make_app,
    stub_path_doctor,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


@pytest.fixture(autouse=True)
def _stub_owners(monkeypatch):
    # The create=True publish path proceeds to the owner picker, which fetches
    # owners over the network; stub it so no scenario hits GitHub.
    monkeypatch.setattr(
        onboard_wizard_flow, "fetch_repo_owners",
        lambda api_url, token: [github_publish.RepoOwner("octocat", "user")],
    )


# --------------------------------------------------------------------------- #
# Publish guard — refuse the create+push unless can_publish is a confirmed True
# --------------------------------------------------------------------------- #


def _verification_with_publish(
    kind: str, can_publish: object, *, can_create: object | None = None
) -> dict:
    # A select-repositories repository-scoped token can create but can't push to a
    # brand-new repo, so can_create stays True while can_publish is False; the
    # default ties create to publish for the simpler scoped_token cases.
    if can_create is None:
        can_create = can_publish
    return {
        "identity": {"login": "machine-user"},
        "access": {"owners": ["machine-user"], "repos": ["machine-user/x"]},
        "capability": {
            "kind": kind,
            "can_create": can_create,
            "create_private": None,
            "can_push_new": can_publish,
            "can_publish": can_publish,
            "writable": [],
            "readonly": [],
            "see_private": 1,
            "see_public": 0,
            "write_probed_count": 0,
            "write_probe_total": 0,
        },
    }


def _body_text(app) -> str:
    from textual.widgets import Static

    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


def _drive_publish_choice(verification: dict | None) -> tuple[object, str]:
    """Run _on_publish_choice(YES) with a connected machine token + verification.

    Returns the app and the rendered body text captured while the app is still
    live (the body Static widgets are unmounted at teardown, so the text must be
    read inside the run_test context).
    """
    app, _spy = make_app()
    captured = {"body": ""}

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app.result.machine_github_token = "ghu_machine_token"
            app.result.machine_github_verification = verification
            app.result.project_checkout = "/home/code/widget"
            app._on_publish_choice(screens.PUBLISH_YES)
            # Two pauses let the call_later body-swap (_apply_pending_swap ->
            # _swap_body) settle so the rendered screen is queryable.
            await pilot.pause()
            await pilot.pause()
            captured["body"] = _body_text(app)

    asyncio.run(scenario())
    return app, captured["body"]


def test_publish_blocked_when_scoped_token_cannot_publish() -> None:
    """A scope-bearing token with no repo scope (can_publish=False) routes to the block."""
    app, body = _drive_publish_choice(
        _verification_with_publish("scoped_token", False)
    )
    assert app.result.project_publish_to_github is False
    assert "can't publish a new repo" in body.lower()


def test_publish_blocked_when_repository_token_select_repositories() -> None:
    """A select-repositories repository-scoped GitHub App user token (can create, can't push) blocks.

    can_publish=False: it can create a repo but cannot push to a brand-new repo
    outside its selected-repositories allowlist, so the create+push is a
    guaranteed failure — refuse before orphaning an empty repo. The block copy
    names the push gap, not a create gap (can_create is True here).
    """
    app, body = _drive_publish_choice(
        _verification_with_publish("repository_token", False, can_create=True)
    )
    assert app.result.project_publish_to_github is False
    assert "can't publish a new repo" in body.lower()
    # names the push/brand-new-repo gap (not a create gap): copy reads
    # "...it can't publish a brand-new repo in one step."
    assert "brand-new repo" in body.lower()


def test_publish_proceeds_when_repository_token_all_repositories() -> None:
    """An "all repositories" repository-scoped GitHub App user token (can_publish=True) proceeds.

    This is the case the old create-only guard wrongly refused: a repository-scoped
    token that CAN push to a brand-new repo is publish-able and proceeds to the
    owner picker.
    """
    app, body = _drive_publish_choice(
        _verification_with_publish("repository_token", True)
    )
    assert app.result.project_publish_to_github is True
    assert "can't publish a new repo" not in body.lower()


def test_publish_proceeds_when_scoped_token_can_publish() -> None:
    """A scope-bearing token with the repo scope (can_publish=True) proceeds to the picker."""
    app, body = _drive_publish_choice(
        _verification_with_publish("scoped_token", True)
    )
    assert app.result.project_publish_to_github is True
    assert "can't publish a new repo" not in body.lower()


def test_publish_block_screen_ack_keeps_it_local() -> None:
    """Acknowledging the block continues local-only with no repo adoption."""
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app.result.machine_github_token = "ghu_machine_token"
            app.result.machine_github_verification = _verification_with_publish(
                "scoped_token", False
            )
            app.result.project_checkout = "/home/code/widget"
            app._on_publish_choice(screens.PUBLISH_YES)  # -> block screen
            await pilot.pause()
            await pilot.pause()
            await pilot.press("enter")  # acknowledge -> _after_repo("")
            await pilot.pause()
            await pilot.pause()

    asyncio.run(scenario())

    assert app.result.project_publish_to_github is False
    assert app.result.project_github_repo is None
    assert app.result.project_github_adoption is None


def test_publish_yes_without_machine_token_still_prompts_for_github_auth() -> None:
    """No connected token: the guard does not block — the user pastes a GitHub App user token next."""
    app, _spy = make_app()
    captured = {"body": ""}

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app.result.machine_github_token = None
            app.result.machine_github_verification = None
            app.result.project_checkout = "/home/code/widget"
            app._on_publish_choice(screens.PUBLISH_YES)
            await pilot.pause()
            await pilot.pause()
            captured["body"] = _body_text(app)

    asyncio.run(scenario())

    # Not blocked — publish stays on and the GitHub App user token prompt (not the block) is shown.
    assert app.result.project_publish_to_github is True
    assert "can't publish a new repo" not in captured["body"].lower()


# --------------------------------------------------------------------------- #
# Publish-only GitHub App user token staleness — declining publish after a back-nav GitHub App user token clears it
# --------------------------------------------------------------------------- #


def test_publish_only_token_cleared_when_publish_later_declined() -> None:
    """A publish-only GitHub auth pasted at the prompt is dropped on a later decline."""
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test():
            app.result.project_checkout = "/home/code/widget"
            # A prior back-nav visit pasted a publish-only GitHub auth — the state
            # _after_publish_github_auth leaves (the owner fetch it also triggers hits
            # the network, so the provenance state is set directly here).
            app.result.machine_github_token = "ghu_publish_token"
            app.result.machine_github_api_url = "https://api.github.com"
            app.result.machine_github_token_source_kind = "prompt"
            app._publish_user_token_only = True
            # The user back-navigates and now declines publish.
            app._on_publish_choice(screens.PUBLISH_NO)

    asyncio.run(scenario())

    assert app.result.machine_github_token is None
    assert app.result.machine_github_api_url is None
    assert app.result.machine_github_token_source_kind is None
    assert app._publish_user_token_only is False


def test_genuine_machine_token_survives_a_later_publish_decline() -> None:
    """A real machine connection is NOT cleared by a later publish decline.

    The provenance flag is reset on a genuine connect, so declining publish
    afterward leaves the connected machine token intact.
    """
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test():
            app.result.project_checkout = "/home/code/widget"
            # A real machine connect ran (sets the token, resets the flag).
            app.result.machine_github_token = "ghu_real_machine"
            app.result.machine_github_api_url = "https://api.github.com"
            app.result.machine_github_token_source_kind = "prompt"
            app._publish_user_token_only = False
            app._on_publish_choice(screens.PUBLISH_NO)

    asyncio.run(scenario())

    assert app.result.machine_github_token == "ghu_real_machine"
