"""Older and misconfigured servers remain reachable through explicit tokens."""

import asyncio
import pytest
from textual.widgets import Input, Static

from runtime.api.cli.onboard_wizard_test_helpers import (
    make_app,
    stub_path_doctor,
    type_text,
)
from yoke_cli.config import team_server_authorization as team
from yoke_cli.config.onboard_wizard import WizardDefaults
from yoke_cli.transport.bounded_json_http import BoundedJsonHttpStatusError


@pytest.mark.parametrize(
    "status,error,reason",
    [
        (404, None, "machine_sign_in_unavailable"),
        (503, "oidc_misconfigured", "oidc_misconfigured"),
    ],
)
def test_discovery_refusal_offers_working_token_entry(
    monkeypatch, status, error, reason
):
    discover = team.browser_sign_in_available
    stub_path_doctor(monkeypatch)
    monkeypatch.setattr(team, "browser_sign_in_available", discover)

    def refused(*args, **kwargs):
        raise BoundedJsonHttpStatusError(status, {"error": error})

    monkeypatch.setattr(team, "request_json", refused)
    app, _ = make_app(
        WizardDefaults(
            config_path="/tmp/cfg.json", env_name="prod", api_url="https://team.example"
        )
    )

    async def scenario():
        async with app.run_test() as pilot:
            app._discover_team_server("https://team.example")
            await app.workers.wait_for_complete()
            await pilot.pause()
            text = " ".join(
                str(widget.render())
                for widget in app.query("#onboard-body Static").results(Static)
            )
            assert reason in text
            assert "Use API token" in text
            assert "Edit connection" in text
            assert "Choose another home" in text
            await pilot.press("enter")
            await pilot.pause()
            assert (
                app.query_one("#onboard-input-server_url", Input).value
                == "https://team.example"
            )
            assert app.query_one("#onboard-input-credential", Input).password
            assert app._machine_authorization_server is None
            await pilot.press("enter")
            await type_text(pilot, "yoke_v1_explicit")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.result.token == "yoke_v1_explicit"
            assert app.result.yoke_token_verification["ok"]

    asyncio.run(scenario())
