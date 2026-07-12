"""Token-verification pilot coverage for the ``yoke onboard`` wizard."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_wizard_flow_connect  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402
from yoke_cli.config.onboard_wizard_widgets import (  # noqa: E402
    STEP_CONNECT,
    STEP_GITHUB,
    STEP_PROJECT,
    Stepper,
)
from yoke_cli.config.yoke_token_verify import (  # noqa: E402
    YokeTokenVerificationError,
)

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
    type_text,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def test_token_prompt_input_is_password() -> None:
    app, _spy = make_app(WizardDefaults(
        config_path="/tmp/cfg.json", env_name="prod", api_url="https://api.test",
    ))

    async def scenario() -> None:
        from textual.widgets import Input

        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")  # token source: paste
            await pilot.pause()
            assert app.query_one("#onboard-input", Input).password is True

    asyncio.run(scenario())


def test_empty_token_prompt_stays_on_input() -> None:
    app, _spy = make_app(WizardDefaults(
        config_path="/tmp/cfg.json", env_name="prod", api_url="https://api.test",
    ))

    async def scenario() -> None:
        from textual.widgets import Input, Static

        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")  # token source: paste
            await pilot.press("enter")  # empty token must not use placeholder
            await pilot.pause()
            assert app.query_one("#onboard-input", Input).password is True
            error = app.query_one(".onboard-input-error", Static)
            assert "A value is required." in str(error.render())
            assert app.result.token is None

    asyncio.run(scenario())


def test_yoke_token_prompt_verifies_before_github() -> None:
    app, _spy = make_app(WizardDefaults(
        config_path="/tmp/cfg.json", env_name="prod", api_url="https://api.test",
    ))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")  # token source: paste
            await type_text(pilot, "yoke_v1_good")
            await pilot.press("enter")
            text = await _wait_for_body_text(app, pilot, "Yoke token connected.")
            assert "Yoke token connected." in text
            assert "Success! You've authenticated with Yoke." in text
            assert "Default Org" in text
            await pilot.press("enter")  # Continue to GitHub
            await pilot.pause()
            assert app.query_one(Stepper).active == STEP_GITHUB
            assert app.result.token == "yoke_v1_good"

    asyncio.run(scenario())


def test_yoke_token_without_org_or_project_access_can_retry(monkeypatch) -> None:
    def no_access(_api_url: str, _token: str) -> dict:
        return {
            "checked": True,
            "ok": True,
            "status": "verified",
            "actor": {"label": "setup-bot"},
            "orgs": [],
            "projects": [],
        }

    monkeypatch.setattr(onboard_wizard_flow_connect, "verify_yoke_token", no_access)
    app, _spy = make_app(WizardDefaults(
        config_path="/tmp/cfg.json", env_name="prod", api_url="https://api.test",
    ))

    async def scenario() -> None:
        from textual.widgets import Input

        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")  # token source: paste
            await type_text(pilot, "yoke_v1_no_access")
            await pilot.press("enter")
            text = await _wait_for_body_text(
                app, pilot, "Yoke token could not be verified.",
            )
            assert app.query_one(Stepper).active == STEP_CONNECT
            assert "Yoke token is valid" in text
            assert "does not include access to any Yoke organization or project" in text
            assert "Ask a Yoke admin" in text
            assert "Try again" in text
            assert app.result.token is None
            assert app.result.yoke_token_verification is None
            await pilot.press("enter")  # Try again
            await pilot.pause()
            assert app.query_one("#onboard-input", Input).password is True

    asyncio.run(scenario())


def test_stored_yoke_token_shows_reuse_feedback(tmp_path) -> None:
    token_file = tmp_path / "stage.token"
    token_file.write_text("yoke_v1_file\n", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({
            "active_env": "stage",
            "connections": {
                "stage": {
                    "transport": "https",
                    "api_url": "https://api.stage.test",
                    "credential_source": {
                        "kind": "token_file",
                        "path": str(token_file),
                    },
                },
            },
        }),
        encoding="utf-8",
    )
    app, _spy = make_app(WizardDefaults(
        config_path=str(config),
        env_name="stage",
    ))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            text = await _wait_for_body_text(app, pilot, "Use this saved Yoke connection?")
            assert "Use this saved Yoke connection?" in text
            await pilot.press("enter")  # reuse saved connection
            text = await _wait_for_body_text(app, pilot, "Yoke token connected.")
            assert "Yoke token connected." in text
            assert "Using existing environment: stage (https://api.stage.test)" in text
            assert "Using existing Yoke token file from machine config." in text

    asyncio.run(scenario())


def test_yoke_token_prompt_error_can_retry(monkeypatch) -> None:
    def reject(_api_url: str, _token: str) -> dict:
        raise YokeTokenVerificationError("API token is unknown")

    monkeypatch.setattr(onboard_wizard_flow_connect, "verify_yoke_token", reject)
    app, _spy = make_app(WizardDefaults(
        config_path="/tmp/cfg.json", env_name="prod", api_url="https://api.test",
    ))

    async def scenario() -> None:
        from textual.widgets import Input

        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")  # token source: paste
            await type_text(pilot, "yoke_v1_bad")
            await pilot.press("enter")
            text = await _wait_for_body_text(
                app, pilot, "Yoke token could not be verified.",
            )
            assert "Yoke token could not be verified." in text
            assert "API token is unknown" in text
            await pilot.press("enter")  # Try again
            await pilot.pause()
            assert app.query_one("#onboard-input", Input).password is True
            assert app.result.token is None

    asyncio.run(scenario())


def test_machine_github_connect_uses_browser_app_flow() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")  # machine github: connect
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one(Stepper).active == STEP_PROJECT
            assert app.result.machine_github_choice == "connect"
            assert app.result.machine_github_verification["ok"] is True
            assert not hasattr(app.result, "machine_github_token")

    asyncio.run(scenario())


def test_stored_github_app_authorization_is_rechecked(tmp_path) -> None:
    credential = tmp_path / "github-app-user.json"
    credential.write_text("{}\n", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({
            "github": {
                "api_url": "https://api.github.com",
                "web_url": "https://github.com",
                "app_slug": "yoke-test",
                "client_id": "Iv1.test",
                "authorization": {
                    "kind": "github_app_user_authorization",
                    "status": "authorized",
                    "refresh_credential_ref": str(credential),
                },
                "installations": [],
                "repositories": [],
            },
        }),
        encoding="utf-8",
    )
    app, _spy = make_app(WizardDefaults(
        config_path=str(config),
        env_name="prod",
        api_url="https://api.test",
        token="actor-token",
    ))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.query_one(Stepper).active == STEP_PROJECT
            assert app.result.machine_github_verification["ok"] is True
            assert not hasattr(app.result, "machine_github_token_file")

    asyncio.run(scenario())


def test_hosted_pick_uses_the_production_url() -> None:
    app, _spy = make_app(WizardDefaults(
        config_path="/tmp/cfg.json", env_name="prod", token="actor-token",
    ))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("up")  # destination picker: wrap local -> upyoke.com
            await pilot.press("enter")
            await pilot.press("enter")  # env select: Production default
            await pilot.pause()
            assert app.result.api_url == "https://api.upyoke.com"
            assert app.query_one(Stepper).active == STEP_GITHUB

    asyncio.run(scenario())


def _body_text(app) -> str:
    from textual.widgets import Static

    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


async def _wait_for_body_text(app, pilot, expected: str) -> str:
    for _ in range(10):
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = _body_text(app)
        if expected in text:
            return text
    return _body_text(app)
