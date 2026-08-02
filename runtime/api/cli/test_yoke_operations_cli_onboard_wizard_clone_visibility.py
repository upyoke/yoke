"""Wizard coverage for the clone public/private split + private repo picker.

After the clone folder the wizard asks whether the repo is public or private.
Public keeps the original paste-URL input; private lists the repos the connected
GitHub App authorization can reach and records the chosen repo's clone URL as the remote.
``build_report`` is spied at the wizard boundary and the private-repo list is
stubbed, so no scenario hits GitHub or git. Without a connected App the
visibility screen is omitted and the clone path stays on the paste-URL input.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_cli.config import github_publish  # noqa: E402
from yoke_cli.config import github_app_machine_access  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_clone as clone_flow  # noqa: E402
from yoke_cli.config import onboard_wizard_project_screens as screens  # noqa: E402
from yoke_cli.config import project_git_probe  # noqa: E402
from yoke_cli.config import project_git_transport  # noqa: E402
from yoke_cli.config.onboard_wizard_widgets import SelectionList  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    make_app,
    stub_path_doctor,
    stub_source_branch,
    type_text,
)
from runtime.api.cli.onboard_wizard_clone_visibility_support import (  # noqa: E402
    body_text,
    start_clone,
    wait_for_body_text,
    wait_for_selection,
)

_PRIVATE_REPOS = [
    github_publish.RepoRef(
        "octocat/secret-lab", "https://github.com/octocat/secret-lab.git", True
    ),
    github_publish.RepoRef(
        "acme-inc/internal", "https://github.com/acme-inc/internal.git", True
    ),
]


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


@pytest.fixture(autouse=True)
def _stub_source_branch(monkeypatch):
    stub_source_branch(monkeypatch, "main")


@pytest.fixture(autouse=True)
def _stub_private_repos(monkeypatch):
    monkeypatch.setattr(
        clone_flow,
        "fetch_private_repos",
        lambda api_url, token, **_kwargs: list(_PRIVATE_REPOS),
    )
    monkeypatch.setattr(
        github_app_machine_access,
        "repository_permission",
        lambda repo, permission, required, config_path: None,
    )


def test_public_clone_routes_to_paste_url_input() -> None:
    """Public visibility lands on the original paste-URL input."""
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await start_clone(app, pilot, connect_github=True)
            await pilot.press("enter")  # visibility: Public (default)
            await pilot.pause()
            # The active view is the paste-URL Input, not a SelectionList.
            from textual.widgets import Input

            inputs = list(app.query("#onboard-body Input").results(Input))
            assert inputs, "public branch should land on the paste-URL input"
            await type_text(pilot, "https://github.com/acme/widgets.git")
            await pilot.press("enter")  # remote -> clone-folder input
            await pilot.press("enter")  # accept default folder -> clone-outcome
            selection = await wait_for_selection(app, pilot)
            # The clone-outcome screen renders after the URL + folder are recorded.
            assert selection.rows
            assert (
                app.result.project_remote_url == "https://github.com/acme/widgets.git"
            )

    asyncio.run(scenario())


def test_private_clone_lists_repos_and_sets_remote_from_pick() -> None:
    """Private visibility shows the repo picker; a pick sets the clone URL remote."""
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await start_clone(app, pilot, connect_github=True)
            await pilot.press("down")  # visibility: move to Private
            await pilot.press("enter")
            selection = await wait_for_selection(app, pilot)
            values = [row.value for row in selection.rows]
            # The rows are the private repos' clone URLs.
            assert values == [r.clone_url for r in _PRIVATE_REPOS]
            await pilot.press("down")  # pick the second private repo
            await pilot.press("enter")
            await pilot.pause()
            assert app.result.project_remote_url == _PRIVATE_REPOS[1].clone_url
            # The pick feeds the post-URL routing: clone-folder input, then outcome.
            await pilot.press("enter")  # accept default folder -> clone-outcome
            outcome = await wait_for_selection(app, pilot)
            assert outcome.rows

    asyncio.run(scenario())


def test_empty_private_repo_access_has_manage_retry_and_back(
    monkeypatch,
) -> None:
    calls = 0

    def fetch(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return [] if calls <= 2 else list(_PRIVATE_REPOS)

    opened: list[str] = []
    monkeypatch.setattr(clone_flow, "fetch_private_repos", fetch)
    monkeypatch.setattr(
        clone_flow.webbrowser,
        "open",
        lambda url: opened.append(url) or True,
    )
    monkeypatch.setattr(
        clone_flow.github_state,
        "repository_access_url",
        lambda _result: "https://github.com/settings/installations/1",
    )
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await start_clone(app, pilot, connect_github=True)
            await pilot.press("down")
            await pilot.press("enter")
            text = await wait_for_body_text(
                app,
                pilot,
                "No private repositories are available to Yoke.",
            )
            assert "Paste" not in text
            assert "GitHub App access URL" in text
            selection = await wait_for_selection(app, pilot)
            assert [row.value for row in selection.rows] == [
                "manage",
                "check",
                "back",
            ]
            await pilot.press("enter")
            await pilot.pause()
            assert opened == ["https://github.com/settings/installations/1"]
            await pilot.press("down", "down")
            await pilot.press("enter")
            await pilot.pause()
            assert "Is the repo public or private?" in body_text(app)
            await pilot.press("down")
            await pilot.press("enter")
            selection = await wait_for_selection(app, pilot)
            assert [row.value for row in selection.rows] == [
                "manage",
                "check",
                "back",
            ]
            await pilot.press("down")
            await pilot.press("enter")
            selection = await wait_for_selection(app, pilot)
            assert [row.value for row in selection.rows] == [
                repo.clone_url for repo in _PRIVATE_REPOS
            ]

    asyncio.run(scenario())


def test_private_repo_error_back_returns_to_visibility_choice(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        clone_flow,
        "fetch_private_repos",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("private repository lookup unavailable")
        ),
    )
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await start_clone(app, pilot, connect_github=True)
            await pilot.press("down")  # visibility: Private
            await pilot.press("enter")
            text = await wait_for_body_text(
                app,
                pilot,
                "Couldn't load private repos",
            )
            assert "Couldn't load private repos" in text
            await pilot.press("down")  # Back
            await pilot.press("enter")
            await pilot.pause(0.2)
            assert "Is the repo public or private?" in body_text(app)

    asyncio.run(scenario())


def test_private_reachability_error_never_falls_back_to_url_input(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        project_git_transport,
        "remote_probe",
        lambda *_args, **_kwargs: project_git_probe.GitRemoteProbe(
            False,
            failure_kind=project_git_probe.FAILURE_ACCESS,
        ),
    )
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await start_clone(app, pilot, connect_github=True)
            await pilot.press("down")
            await pilot.press("enter")
            picker = await wait_for_selection(app, pilot)
            assert picker.rows[0].value == _PRIVATE_REPOS[0].clone_url
            await pilot.press("enter")
            text = await wait_for_body_text(app, pilot, "Couldn't reach that repo.")
            assert "Change URL" not in text
            from textual.widgets import Input

            assert not list(app.query("#onboard-body Input").results(Input))
            recovery = await wait_for_selection(app, pilot)
            assert [row.value for row in recovery.rows] == [
                "repositories",
                "retry",
                "back",
            ]
            await pilot.press("enter")
            refreshed = await wait_for_selection(app, pilot)
            assert [row.value for row in refreshed.rows] == [
                repo.clone_url for repo in _PRIVATE_REPOS
            ]

    asyncio.run(scenario())


def test_no_app_connection_omits_visibility_and_uses_paste_url() -> None:
    """Without an App connection the visibility screen is skipped (no dead-end)."""
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await start_clone(app, pilot, connect_github=False)
            await pilot.pause()
            # No visibility SelectionList — the clone path is straight on the
            # paste-URL Input because no App connection can list private repos.
            from textual.widgets import Input

            inputs = list(app.query("#onboard-body Input").results(Input))
            assert inputs, "no-token clone should land directly on paste-URL input"
            selection = list(
                app.query("#onboard-body SelectionList").results(SelectionList)
            )
            assert not selection, "no visibility screen without an App connection"
            await type_text(pilot, "https://github.com/acme/widgets.git")
            await pilot.press("enter")
            await pilot.pause()
            assert (
                app.result.project_remote_url == "https://github.com/acme/widgets.git"
            )

    asyncio.run(scenario())


def test_repo_rows_carry_clone_url_value_and_full_name_label() -> None:
    """The picker rows expose the clone URL as value and full name as label."""
    rows = screens.repo_rows(_PRIVATE_REPOS)
    assert [r.value for r in rows] == [r.clone_url for r in _PRIVATE_REPOS]
    assert [r.label for r in rows] == [r.full_name for r in _PRIVATE_REPOS]
