from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("textual")

from yoke_cli.config import hosted_machine_authorization  # noqa: E402
from yoke_cli.config import onboard_destinations  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_connect  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_hosted_machine  # noqa: E402
from yoke_cli.config import writer  # noqa: E402
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
    assert resolve(connect_url="https://app.upyoke.com.evil.example/api/orgs/acme") == (
        onboard_destinations.DESTINATION_SERVER,
        "https://app.upyoke.com.evil.example/api/orgs/acme",
    )
    matches = onboard_destinations.matches_stored_hosted_authority
    assert matches(
        "https://app.upyoke.com",
        "https://app.upyoke.com/api/orgs/acme",
    )
    assert not matches(
        "https://app.upyoke.com.evil.example",
        "https://app.upyoke.com/api/orgs/acme",
    )
    assert not matches(
        "https://api.stage.upyoke.com",
        "https://api.upyoke.com",
    )


@pytest.mark.parametrize("preset_token", [None, "legacy-hosted-token"])
def test_hosted_url_preset_starts_browser_approval_without_token_entry(
    monkeypatch,
    preset_token: str | None,
) -> None:
    pending = hosted_machine_authorization.PendingMachineAuthorization(
        platform_url="https://app.upyoke.com",
        device_code="device-secret",
        user_code="ABCD-2345",
        verification_uri="https://app.upyoke.com/machine",
        verification_uri_complete="https://app.upyoke.com/machine?user_code=ABCD-2345",
        expires_in=600,
        interval=2,
    )
    starts: list[str] = []
    monkeypatch.setattr(
        hosted_machine_authorization,
        "start",
        lambda url: starts.append(url) or pending,
    )
    monkeypatch.setattr(hosted_machine_authorization, "open_browser", lambda _: False)
    app, _spy = make_app(
        WizardDefaults(
            config_path="/tmp/cfg.json",
            env_name="prod",
            api_url="https://app.upyoke.com",
            destination=onboard_destinations.DESTINATION_HOSTED,
            token=preset_token,
        )
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            assert "Which hosted environment should this machine use?" in _body_text(
                app
            )
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            body = _body_text(app)
            assert "Sign in and choose an organization." in body
            assert "ABCD-2345" in body
            assert "Provide your Yoke API token" not in body
            assert app.result.token is None
            assert starts == ["https://app.upyoke.com"]

    asyncio.run(scenario())


def test_hosted_pick_persists_browser_approval_before_project_flow(
    tmp_path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
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
    app, _spy = make_app(WizardDefaults(config_path=str(config), env_name="prod"))

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
            assert app.result.token is None
            assert app.result.token_source_kind == "token_file"
            token_file = app.result.token_file
            assert token_file is not None
            assert Path(token_file).read_text(encoding="utf-8").strip() == (
                "tenant-actor-token"
            )
            payload = json.loads(config.read_text(encoding="utf-8"))
            assert payload["active_env"] == "acme"
            assert payload["connections"]["acme"] == {
                "transport": "https",
                "api_url": "https://app.upyoke.com/api/orgs/acme",
                "credential_source": {
                    "kind": "token_file",
                    "path": token_file,
                },
            }
            await pilot.press("enter")
            assert app.query_one(Stepper).active == STEP_GITHUB

    asyncio.run(scenario())


def test_hosted_selector_reuses_persisted_tenant_connection(
    tmp_path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    writer.set_connection(
        "acme",
        transport="https",
        api_url="https://app.upyoke.com/api/orgs/acme",
        token="persisted-tenant-actor-token",
        activate=True,
        path=config,
    )
    monkeypatch.setattr(
        hosted_machine_authorization,
        "start",
        lambda _url: pytest.fail("stored hosted connection started a new code"),
    )
    monkeypatch.setattr(
        onboard_wizard_flow_connect,
        "verify_yoke_token",
        lambda api_url, token: {
            "ok": True,
            "actor": {"label": "test-actor"},
            "orgs": [{"name": "Acme"}],
            "projects": [{"slug": "demo"}],
            "verified_api_url": api_url,
            "verified_token": token,
        },
    )
    app, _spy = make_app(
        WizardDefaults(
            config_path=str(config),
            api_url="https://app.upyoke.com",
            destination=onboard_destinations.DESTINATION_HOSTED,
        )
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await app.workers.wait_for_complete()
            assert "Yoke token connected." in _body_text(app)
            assert app.result.env_name == "acme"
            assert app.result.api_url == "https://app.upyoke.com/api/orgs/acme"
            assert app.result.token_file == str(home / "secrets" / "acme.token")

    asyncio.run(scenario())


def test_browser_connection_write_atomically_activates_existing_env(
    tmp_path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    writer.set_connection(
        "first", transport="https", api_url="https://api.upyoke.com",
        token="yoke_v1_first_secret", path=config,
    )
    writer.set_connection(
        "second", transport="https", api_url="https://api.stage.upyoke.com",
        token="yoke_v1_second_secret", activate=True, path=config,
    )

    payload = json.loads(config.read_text(encoding="utf-8"))
    assert payload["active_env"] == "second"


def test_hosted_failure_retries_browser_flow_without_teaching_token_paste(
    monkeypatch,
) -> None:
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

    def fail_complete(_pending) -> None:
        raise hosted_machine_authorization.HostedMachineAuthorizationError(
            "approval expired"
        )

    monkeypatch.setattr(hosted_machine_authorization, "complete", fail_complete)
    app, _spy = make_app(WizardDefaults(config_path="/tmp/cfg.json", env_name="prod"))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("up", "enter", "enter")
            await app.workers.wait_for_complete()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            body = _body_text(app)
            assert "start a fresh browser sign-in" in body
            assert "paste a different token" not in body

    asyncio.run(scenario())
