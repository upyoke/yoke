from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_cli.config import hosted_machine_authorization  # noqa: E402
from yoke_cli.config import onboard_destinations  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_hosted_machine  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT, STEP_GITHUB, Stepper  # noqa: E402

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


def test_org_api_authority_is_hosted_without_trusting_lookalike_origins() -> None:
    resolve = onboard_destinations.resolve_choice
    assert resolve(connect_url="https://app.upyoke.com/api/orgs/acme") == (
        onboard_destinations.DESTINATION_HOSTED,
        "https://app.upyoke.com/api/orgs/acme",
    )
    assert resolve(
        connect_url="https://app.upyoke.com.evil.example/api/orgs/acme"
    ) == (
        onboard_destinations.DESTINATION_SERVER,
        "https://app.upyoke.com.evil.example/api/orgs/acme",
    )


def test_hosted_pick_uses_browser_approval_and_selected_org(monkeypatch) -> None:
    pending = hosted_machine_authorization.PendingMachineAuthorization(
        platform_url="https://app.upyoke.com",
        device_code="device-secret",
        user_code="ABCD-2345",
        verification_uri="https://app.upyoke.com/machine",
        verification_uri_complete="https://app.upyoke.com/machine?user_code=ABCD-2345",
        expires_in=600,
        interval=2,
    )
    monkeypatch.setattr(hosted_machine_authorization, "start", lambda _url: pending)
    monkeypatch.setattr(hosted_machine_authorization, "open_browser", lambda _: True)
    monkeypatch.setattr(
        hosted_machine_authorization,
        "complete",
        lambda _: hosted_machine_authorization.HostedMachineCredential(
            api_url="https://app.upyoke.com/api/orgs/acme",
            org="acme",
            token="tenant-actor-token",
        ),
    )
    monkeypatch.setattr(
        onboard_wizard_flow_hosted_machine.yoke_token_verify,
        "verify",
        lambda _url, _token: {
            "ok": True,
            "actor": {"label": "test-actor"},
            "orgs": [{"name": "Acme"}],
            "projects": [{"slug": "demo"}],
        },
    )
    app, _spy = make_app(WizardDefaults(config_path="/tmp/cfg.json", env_name="prod"))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("up", "enter", "enter")
            await app.workers.wait_for_complete()
            assert "Sign in and choose an organization." in _body_text(app)
            assert "ABCD-2345" in _body_text(app)
            assert app.query_one(Stepper).active == STEP_CONNECT
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert "Yoke token connected." in _body_text(app)
            assert app.result.api_url == "https://app.upyoke.com/api/orgs/acme"
            assert app.result.env_name == "acme"
            assert app.result.token == "tenant-actor-token"
            await pilot.press("enter")
            assert app.query_one(Stepper).active == STEP_GITHUB

    asyncio.run(scenario())
