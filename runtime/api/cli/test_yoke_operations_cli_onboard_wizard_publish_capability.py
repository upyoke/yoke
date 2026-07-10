"""Wizard coverage for least-privilege GitHub App repository publishing."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_contracts import github_origin  # noqa: E402
from yoke_cli.config import github_publish  # noqa: E402
from yoke_cli.config import machine_config  # noqa: E402
from yoke_cli.config import onboard_machine_github  # noqa: E402
from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_flow  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_github  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_publish as publish_flow  # noqa: E402
from yoke_cli.config import onboard_wizard_project_screens as screens  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    complete_board_art,
    make_app,
    stub_path_doctor,
    type_text,
)


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    stub_path_doctor(monkeypatch)
    monkeypatch.setattr(
        onboard_wizard_flow,
        "fetch_repo_owners",
        lambda _api_url, _token: [github_publish.RepoOwner("octocat", "user")],
    )
    monkeypatch.setattr(
        publish_flow, "user_access_token", lambda _result: "short-lived-publish-access",
    )


def _github_config(*, administration: bool, suspended: bool = False) -> dict:
    permissions = {"administration": "write"} if administration else {}
    return {"installations": [{
        "installation_id": 7, "account_login": "octocat",
        "permissions": permissions, "suspended": suspended,
    }]}


def _body_text(app) -> str:
    from textual.widgets import Static

    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


def test_unavailable_app_publish_opens_github_and_keeps_project_local(
    monkeypatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        onboard_wizard_flow_github.github_machine,
        "connect",
        lambda **_: {
            "ok": False,
            "issues": [{"message": "GitHub App configuration is unavailable."}],
        },
    )
    monkeypatch.setattr(publish_flow.webbrowser, "open", opened.append)
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")  # machine GitHub: connect (default)
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("enter")  # App flow unavailable: backlog-only
            mode_index = next(
                i for i, row in enumerate(steps.MODE_ROWS)
                if row.value == onboard_project.PROJECT_MODE_CREATE_REPO
            )
            for _ in range(mode_index):
                await pilot.press("down")
            await pilot.press("enter")  # project mode: create-repo
            await type_text(pilot, "/home/code/demo")
            await pilot.press("enter")
            await pilot.press("enter")  # slug placeholder -> demo
            await pilot.press("enter")  # name placeholder
            await pilot.press("enter")  # publish: Yes (preselected)
            await pilot.press("enter")  # App publishing unavailable: backlog-only
            await pilot.press("enter")  # default branch main
            await pilot.press("enter")  # prefix placeholder
            await complete_board_art(pilot)
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["machine_github_choice"] == onboard_machine_github.CHOICE_SKIP
    assert "machine_github_token" not in applied
    assert "project_github_token" not in applied
    assert applied["project_github_adoption"] is None
    assert applied["project_github_repo"] is None
    assert applied["project_publish"] is None
    assert opened == [f"{github_origin.DEFAULT_GITHUB_WEB_URL}/new"]


def test_default_app_grant_opens_github_and_keeps_project_local(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(machine_config, "github_config", lambda _path: _github_config(
        administration=False,
    ))
    monkeypatch.setattr(publish_flow.webbrowser, "open", opened.append)
    app, _spy = make_app()
    captured = {"body": ""}

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app.result.machine_github_verification = {"ok": True}
            app.result.project_checkout = "/home/code/widget"
            app._on_publish_choice(screens.PUBLISH_YES)
            await pilot.pause()
            await pilot.pause()
            captured["body"] = _body_text(app)
            await pilot.press("enter")

    asyncio.run(scenario())

    assert opened == [f"{github_origin.DEFAULT_GITHUB_WEB_URL}/new"]
    assert "Administration permission" in captured["body"]
    assert app.result.project_publish_to_github is False
    assert app.result.project_github_repo is None


def test_optional_administration_grant_allows_owner_picker(monkeypatch) -> None:
    monkeypatch.setattr(machine_config, "github_config", lambda _path: _github_config(
        administration=True,
    ))
    app, _spy = make_app()
    captured = {"body": ""}

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app.result.machine_github_verification = {"ok": True}
            app.result.machine_github_api_url = github_origin.DEFAULT_GITHUB_API_URL
            app.result.project_checkout = "/home/code/widget"
            app._on_publish_choice(screens.PUBLISH_YES)
            await app.workers.wait_for_complete()
            await pilot.pause()
            captured["body"] = _body_text(app)

    asyncio.run(scenario())

    assert app.result.project_publish_to_github is True
    assert "octocat" in captured["body"]


def test_suspended_administration_installation_never_opens_empty_owner_picker(
    monkeypatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(machine_config, "github_config", lambda _path: _github_config(
        administration=True, suspended=True,
    ))
    monkeypatch.setattr(publish_flow.webbrowser, "open", opened.append)
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app.result.machine_github_verification = {"ok": True}
            app.result.project_checkout = "/home/code/widget"
            app._on_publish_choice(screens.PUBLISH_YES)
            await pilot.pause()
            assert "Administration permission" in _body_text(app)
            await pilot.press("enter")

    asyncio.run(scenario())

    assert opened == [f"{github_origin.DEFAULT_GITHUB_WEB_URL}/new"]
    assert app.result.project_publish_to_github is False
    assert not getattr(app, "_owner_lookup", {})


def test_wizard_result_has_no_github_credential_state() -> None:
    app, _spy = make_app()

    assert not hasattr(app.result, "machine_github_token")
    assert not hasattr(app.result, "machine_github_token_file")
    assert not hasattr(app.result, "project_github_token")
