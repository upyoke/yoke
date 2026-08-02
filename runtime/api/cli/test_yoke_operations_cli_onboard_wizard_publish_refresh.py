"""Repository-refresh coverage for onboarding publication."""

from __future__ import annotations

import asyncio

import pytest

from runtime.api.cli.test_yoke_operations_cli_onboard_wizard_publish_capability import (
    _body_text,
    _github_config,
    _mark_connected,
    _stubs as _source_stubs,
    complete_board_art,
    github_origin,
    machine_config,
    make_app,
    onboard_project,
    publish_flow,
    screens,
    skip_hosting,
)
from yoke_cli.config import onboard_wizard_flow_publish_manual as manual_flow
from yoke_cli.config import onboard_destinations


@pytest.fixture(autouse=True)
def publish_stubs(monkeypatch):
    _source_stubs.__wrapped__(monkeypatch)


def test_manual_create_refresh_selects_exact_repo_and_continues_in_run(
    monkeypatch,
) -> None:
    opened: list[str] = []
    github = _github_config(administration=False)
    github["api_url"] = github_origin.DEFAULT_GITHUB_API_URL
    github["web_url"] = github_origin.DEFAULT_GITHUB_WEB_URL
    github["repositories"] = [
        {
            "repository_id": 81,
            "installation_id": 7,
            "full_name": "acme/manual-target",
            "default_branch": "main",
            "private": True,
        },
        {
            "repository_id": 82,
            "installation_id": 7,
            "full_name": "other/widget",
            "default_branch": "main",
            "private": False,
        },
    ]
    github["installations"][0].update(
        {"account_login": "acme", "permissions": {"contents": "write"}}
    )
    monkeypatch.setattr(machine_config, "github_config", lambda _path: github)
    monkeypatch.setattr(publish_flow.webbrowser, "open", opened.append)
    report = {
        "ok": True,
        "ready": True,
        "api_url": github_origin.DEFAULT_GITHUB_API_URL,
        "identity": {"checked": True, "ok": True, "login": "octocat"},
        "access": {
            "repo_listing_ok": True,
            "installations": github["installations"],
            "repositories": github["repositories"],
        },
    }
    monkeypatch.setattr(manual_flow.github_machine, "status", lambda **_kwargs: report)
    app, spy = make_app()
    _mark_connected(app)
    app.result.project_mode = onboard_project.PROJECT_MODE_CREATE_REPO
    app.result.project_checkout = "/home/code/widget"
    app.result.project_slug = "widget"
    app.result.project_name = "Widget"
    app.result.destination = onboard_destinations.DESTINATION_LOCAL
    app.result.api_url = ""

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app._on_publish_choice(screens.PUBLISH_YES)
            await pilot.pause()
            assert "Check repositories" in _body_text(app)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            body = _body_text(app)
            assert "acme/manual-target" in body
            assert "other/widget" in body
            for _ in range(5):
                await pilot.press("enter")
            await complete_board_art(pilot)
            await skip_hosting(pilot)
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(scenario())
    applied = spy.applied
    assert applied is not None
    assert opened == [f"{github_origin.DEFAULT_GITHUB_WEB_URL}/new"]
    assert applied["project_github_repo"] == "acme/manual-target"
    assert applied["project_github_adoption"] == "app-binding"
    publish = applied["project_publish"]
    assert publish.full_name == "acme/manual-target"
    assert publish.create_repository is False
    assert publish.private is True
    assert publish.repository_id == 81
    assert publish.installation_id == 7
