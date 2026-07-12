"""Wizard routing for repositories whose identity exists only after Apply."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_cli.config import machine_config  # noqa: E402
from yoke_cli.config import onboard_machine_github  # noqa: E402
from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_github_plan as github_plan  # noqa: E402
from yoke_cli.config import project_clone_support as clone_support  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    make_app,
    stub_path_doctor,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch) -> None:
    stub_path_doctor(monkeypatch)


def _mark_connected(app) -> None:
    app.result.machine_github_choice = onboard_machine_github.CHOICE_CONNECT
    app.result.machine_github_verification = {"ok": True, "ready": True}
    app.result.machine_github_api_url = "https://api.github.com"


def _body_text(app) -> str:
    from textual.widgets import Static

    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


def test_future_created_repository_defers_binding_identity_until_apply(
    monkeypatch,
) -> None:
    github = {
        "repositories": [],
        "installations": [{
            "installation_id": 7,
            "account_login": "octocat",
            "permissions": {"administration": "write"},
            "suspended": False,
            "repository_selection": "all",
        }],
    }
    monkeypatch.setattr(machine_config, "github_config", lambda _path: github)
    app, _spy = make_app()
    _mark_connected(app)
    app.result.project_mode = onboard_project.PROJECT_MODE_CREATE_REPO
    app.result.project_github_repo = "octocat/widget"
    app.result.project_publish_to_github = True
    app.result.project_publish_create_repository = True
    app.result.project_publish_owner = "octocat"
    app.result.project_publish_owner_login = "octocat"
    app.result.project_publish_repo_name = "widget"

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app._after_prefix("WIDG")
            await pilot.pause()
            assert "Give your board a face" in _body_text(app)

    asyncio.run(scenario())

    assert app.result.project_github_adoption == "app-binding"
    assert app.result.project_github_repository_id is None
    assert app.result.project_github_installation_id is None
    publish = github_plan.build_publish_request(app.result)
    assert publish.create_repository is True
    assert publish.repository_id is None
    assert publish.installation_id is None


def test_future_fork_discards_source_binding_identity() -> None:
    app, _spy = make_app()
    _mark_connected(app)
    app.result.project_mode = onboard_project.PROJECT_MODE_CLONE_REMOTE
    app.result.project_clone_outcome = clone_support.CLONE_OUTCOME_FORK
    app.result.project_github_repo = "source/widgets"
    app.result.project_github_repository_id = 41
    app.result.project_github_installation_id = 7

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app._after_prefix("WIDG")
            await pilot.pause()
            assert "Give your board a face" in _body_text(app)

    asyncio.run(scenario())

    assert app.result.project_github_adoption == "app-binding"
    assert app.result.project_github_repository_id is None
    assert app.result.project_github_installation_id is None
