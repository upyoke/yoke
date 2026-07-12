"""Wizard coverage for clone-outcome row visibility and the private picker.

The clone-outcome screen drops the "Fork it" row for non-github remotes and for
any remote when no token is connected (fork parses the source host and
authenticates the fork API call). An empty private-repo list routes to App-access
recovery without accepting an unusable URL. ``build_report`` is spied at the wizard
boundary and the owner list is stubbed, so no scenario hits GitHub or git.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_cli.config import github_publish  # noqa: E402
from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_flow  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_clone  # noqa: E402
from yoke_cli.config import onboard_wizard_project_screens as screens  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config import project_clone_support as clone  # noqa: E402
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
    monkeypatch.setattr(
        onboard_wizard_flow, "fetch_repo_owners",
        lambda api_url, token: [
            github_publish.RepoOwner("octocat", "user"),
            github_publish.RepoOwner("acme-inc", "organization"),
        ],
    )


async def _connect_machine_github_auth(app, pilot) -> None:
    await advance_past_path(pilot)
    await pilot.press("enter")  # machine github: connect account default
    await app.workers.wait_for_complete()
    await pilot.pause()
    await pilot.press("enter")  # confirm connected identity and App access
    await pilot.pause()


async def _pick_mode(pilot, value: str) -> None:
    index = next(i for i, r in enumerate(steps.MODE_ROWS) if r.value == value)
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")


# --------------------------------------------------------------------------- #
# Bug B — "Fork it" offered for non-github remotes
# --------------------------------------------------------------------------- #


def test_clone_outcome_rows_omit_fork_for_non_github_remote() -> None:
    """Fork needs a github.com owner/repo; drop the row for any other host.

    just-clone and make-it-mine stay for all remotes — only fork parses the
    source host and would raise at apply for a non-github URL.
    """
    rows = screens.clone_outcome_rows("https://gitlab.com/acme/widgets.git")
    values = [row.value for row in rows]
    assert clone.CLONE_OUTCOME_FORK not in values
    assert clone.CLONE_OUTCOME_JUST_CLONE in values
    assert clone.CLONE_OUTCOME_MAKE_IT_MINE in values


def test_clone_outcome_rows_keep_fork_for_github_remote() -> None:
    """A github.com remote (read-only variant) keeps all three outcomes."""
    rows = screens.clone_outcome_rows("https://github.com/acme/widgets.git")
    values = [row.value for row in rows]
    assert clone.CLONE_OUTCOME_FORK in values
    assert clone.CLONE_OUTCOME_JUST_CLONE in values
    assert clone.CLONE_OUTCOME_MAKE_IT_MINE in values


def test_clone_outcome_rows_use_configured_ghes_origin() -> None:
    rows = screens.clone_outcome_rows(
        "git@ghe.example:acme/widgets.git",
        web_url="https://ghe.example",
    )
    assert clone.CLONE_OUTCOME_FORK in [row.value for row in rows]
    assert screens.default_repo(
        "https://ghe.example/acme/widgets.git",
        web_url="https://ghe.example",
    ) == "acme/widgets"
    assert screens.default_repo(
        "https://other.example/acme/widgets.git",
        web_url="https://ghe.example",
    ) is None


def test_writable_variant_is_two_rows_clone_default() -> None:
    """push_access True -> Clone it + Duplicate it, Clone it first (no fork)."""
    rows = screens.clone_outcome_rows(
        "https://github.com/acme/widgets.git", push_access=True
    )
    values = [row.value for row in rows]
    assert values == [clone.CLONE_OUTCOME_JUST_CLONE, clone.CLONE_OUTCOME_MAKE_IT_MINE]
    assert rows[0].label == "Clone it"
    assert rows[0].hint == "push straight back to acme/widgets"
    assert rows[1].label == "Duplicate it"
    assert rows[1].hint == "push to a new remote repo we'll create"


def test_readonly_variant_is_three_rows_clone_default() -> None:
    """push_access False -> Clone it + Duplicate it + Fork it, Clone it first."""
    rows = screens.clone_outcome_rows(
        "https://github.com/acme/widgets.git", push_access=False
    )
    values = [row.value for row in rows]
    assert values == [
        clone.CLONE_OUTCOME_JUST_CLONE,
        clone.CLONE_OUTCOME_MAKE_IT_MINE,
        clone.CLONE_OUTCOME_FORK,
    ]
    assert rows[0].label == "Clone it"
    assert rows[0].hint == "push nowhere — read-only access to acme/widgets"
    assert rows[2].label == "Fork it"
    assert rows[2].hint == (
        "push to a new fork we'll create — open PRs back to acme/widgets"
    )


def test_unknown_push_access_uses_readonly_variant() -> None:
    """An unknown probe result (None) shows the safe read-only variant."""
    rows = screens.clone_outcome_rows(
        "https://github.com/acme/widgets.git", push_access=None
    )
    assert rows[0].hint == "push nowhere — read-only access to acme/widgets"
    assert clone.CLONE_OUTCOME_FORK in [row.value for row in rows]


def test_writable_variant_drops_fork_even_when_forkable() -> None:
    """Fork only lives in the read-only variant; writable never shows it."""
    rows = screens.clone_outcome_rows(
        "https://github.com/acme/widgets.git", push_access=True, has_token=True
    )
    assert clone.CLONE_OUTCOME_FORK not in [row.value for row in rows]


def test_clone_outcome_body_title_only_no_subtitle() -> None:
    """The clone-outcome screen renders the title and drops the subtitle."""
    bodies = screens.clone_outcome_body("https://github.com/acme/widgets.git")
    text = " ".join(str(w.render()) for w in bodies)
    assert "How do you want to copy acme/widgets?" in text
    # No "onboard-subtitle" Static is built when the subtitle is None.
    classes = [
        cls
        for w in bodies
        for cls in (getattr(w, "classes", set()) or set())
    ]
    assert "onboard-subtitle" not in classes


def test_clone_outcome_screen_writable_variant_drops_fork(monkeypatch) -> None:
    """A writable token (probe True) renders the 2-row writable screen."""
    from yoke_cli.config import onboard_wizard_flow_clone as clone_flow

    monkeypatch.setattr(
        clone_flow.CloneFlow, "_source_push_access", lambda self: True
    )
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _connect_machine_github_auth(app, pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await pilot.press("enter")  # visibility: Public -> paste-URL input
            await type_text(pilot, "https://github.com/acme/widgets.git")
            await pilot.press("enter")  # remote -> clone-folder input
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("enter")  # accept default folder -> clone-outcome screen
            await pilot.pause()
            selection = app.query_one("#onboard-body SelectionList", SelectionList)
            values = [row.value for row in selection.rows]
            assert values == [
                clone.CLONE_OUTCOME_JUST_CLONE, clone.CLONE_OUTCOME_MAKE_IT_MINE,
            ]
            assert selection.cursor == 0  # Clone it pre-selected

    asyncio.run(scenario())


def test_clone_outcome_rows_omit_fork_without_token_even_for_github() -> None:
    """Fork needs a connected token (it authenticates the fork API call).

    Without a token the row is dropped even for a github.com remote so the
    review never offers an outcome that 403s at apply.
    """
    rows = screens.clone_outcome_rows(
        "https://github.com/acme/widgets.git", has_token=False
    )
    values = [row.value for row in rows]
    assert clone.CLONE_OUTCOME_FORK not in values
    assert clone.CLONE_OUTCOME_JUST_CLONE in values
    assert clone.CLONE_OUTCOME_MAKE_IT_MINE in values


def test_clone_outcome_body_threads_has_token_flag() -> None:
    """clone_outcome_body forwards has_token so the fork row is hidden."""
    bodies = screens.clone_outcome_body(
        "https://github.com/acme/widgets.git", has_token=False
    )
    text = " ".join(str(w.render()) for w in bodies)
    assert "Fork it" not in text


def test_empty_private_repo_picker_requires_app_access(monkeypatch) -> None:
    """An empty private list offers App access recovery, never URL paste."""
    monkeypatch.setattr(
        onboard_wizard_flow_clone, "fetch_private_repos",
        lambda api_url, token, **_kwargs: [],
    )
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _connect_machine_github_auth(app, pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await pilot.press("down")   # visibility: move to Private
            await pilot.press("enter")
            await pilot.pause()
            from textual.widgets import Input

            assert not list(app.query("#onboard-body Input").results(Input))
            selection = app.query_one(
                "#onboard-body SelectionList", SelectionList,
            )
            assert [row.value for row in selection.rows] == [
                "manage", "check", "back",
            ]

    asyncio.run(scenario())


def test_clone_outcome_screen_drops_fork_row_for_non_github_remote() -> None:
    """The live clone-outcome screen omits the fork row for a gitlab remote."""
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _connect_machine_github_auth(app, pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await pilot.press("enter")  # visibility: Public -> paste-URL input
            await type_text(pilot, "https://gitlab.com/acme/widgets.git")
            await pilot.press("enter")  # remote -> clone-folder input
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("enter")  # accept default folder -> clone-outcome screen
            await pilot.pause()
            selection = app.query_one("#onboard-body SelectionList", SelectionList)
            values = [row.value for row in selection.rows]
            assert clone.CLONE_OUTCOME_FORK not in values
            assert clone.CLONE_OUTCOME_JUST_CLONE in values
            assert clone.CLONE_OUTCOME_MAKE_IT_MINE in values

    asyncio.run(scenario())


def test_prior_partial_clone_offers_resume_then_continues(monkeypatch) -> None:
    """A folder that already holds a matching clone routes to Resume vs Start over.

    The clone-folder step detects the prior partial run and shows the Resume /
    Start-over screen instead of the inline "already has files" rejection; Resume
    continues into the normal outcome flow (the resumable apply skips the clone).
    """
    from textual.widgets import Static

    # Treat the typed folder as an already-present clone of the chosen source.
    monkeypatch.setattr(
        clone, "existing_clone_matches", lambda root, remote, **_kwargs: True
    )

    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _connect_machine_github_auth(app, pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await pilot.press("enter")  # visibility: Public -> paste-URL input
            await type_text(pilot, "https://github.com/acme/widgets.git")
            await pilot.press("enter")  # remote -> clone-folder input
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("enter")  # accept default folder -> Resume screen
            await pilot.pause()
            body = " ".join(
                str(w.render())
                for w in app.query("#onboard-body Static").results(Static)
            )
            assert "already has this repo" in body.lower()
            selection = app.query_one("#onboard-body SelectionList", SelectionList)
            assert [r.value for r in selection.rows] == ["resume", "choose-folder"]
            await pilot.press("enter")  # Resume (first row) -> clone-outcome screen
            await app.workers.wait_for_complete()
            await pilot.pause()
            title = next(
                str(w.render()) for w in app.query(".onboard-title").results(Static)
            )
            assert "how do you want to copy" in title.lower()

    asyncio.run(scenario())
