"""GitHub App connection summary and stored authorization behavior."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("textual")

from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402
from yoke_cli.config.onboard_wizard_widgets import (  # noqa: E402
    STEP_GITHUB,
    STEP_PROJECT,
    Stepper,
)
from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def _body_text(app) -> str:
    from textual.widgets import Static

    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


def test_machine_github_connect_uses_browser_app_flow() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            text = _body_text(app)
            assert "GitHub connected." in text
            assert "GitHub user: machine-user · App: yoke-product" in text
            assert "Access: 2 installations · 2 repositories" in text
            assert "Required permissions: ready" in text
            assert "machine-user/private-tool" not in text
            await pilot.press("down", "enter")
            await pilot.pause()
            details = _body_text(app)
            assert "machine-user/private-tool" in details
            assert "Change repository access on GitHub" in details
            assert app.query_one(Stepper).active == STEP_GITHUB
            await pilot.press("escape")
            await pilot.pause()
            assert "Connect GitHub" in _body_text(app)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "GitHub connected." in _body_text(app)
            await pilot.press("enter")
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
        json.dumps(
            {
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
                }
            }
        ),
        encoding="utf-8",
    )
    app, _spy = make_app(
        WizardDefaults(
            config_path=str(config),
            env_name="prod",
            api_url="https://api.test",
            token="actor-token",
        )
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "GitHub connected." in _body_text(app)
            assert app.query_one(Stepper).active == STEP_GITHUB
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one(Stepper).active == STEP_PROJECT
            assert app.result.machine_github_verification["ok"] is True
            assert not hasattr(app.result, "machine_github_token_file")

    asyncio.run(scenario())
