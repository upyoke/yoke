"""Failure and retry behavior for hosted machine authorization."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_cli.config import hosted_machine_authorization  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
)

BROWSER_OPENED = hosted_machine_authorization.BrowserOpenResult(
    opened=True,
    method="webbrowser",
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


def _pending(path: str):
    return hosted_machine_authorization.PendingMachineAuthorization(
        platform_url="https://app.upyoke.com",
        device_code="device-secret",
        user_code="ABCD-2345",
        verification_uri=f"https://app.upyoke.com/{path}",
        verification_uri_complete=(
            f"https://app.upyoke.com/{path}?user_code=ABCD-2345"
        ),
        expires_in=600,
        interval=2,
    )


def test_browser_denial_reports_and_mints_one_fresh_authorization(monkeypatch) -> None:
    pending = _pending("connect")
    starts: list[str] = []
    monkeypatch.setattr(
        hosted_machine_authorization,
        "start",
        lambda url: starts.append(url) or pending,
    )
    monkeypatch.setattr(
        hosted_machine_authorization, "open_browser", lambda _: BROWSER_OPENED
    )

    def deny_complete(_pending, **_kwargs) -> None:
        raise hosted_machine_authorization.HostedMachineAuthorizationDenied(
            "authorization denied in the browser"
        )

    monkeypatch.setattr(hosted_machine_authorization, "complete", deny_complete)
    app, _spy = make_app(WizardDefaults(config_path="/tmp/cfg.json", env_name="prod"))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("up", "enter")
            await app.workers.wait_for_complete()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert len(starts) == 2
            assert "Sign in and choose an organization." in _body_text(app)
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert len(starts) == 2
            body = _body_text(app)
            assert "authorization denied in the browser" in body
            assert "start a fresh browser sign-in" in body

    asyncio.run(scenario())


def test_hosted_failure_retries_browser_flow_without_teaching_token_paste(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        hosted_machine_authorization, "start", lambda _url: _pending("machine")
    )
    monkeypatch.setattr(
        hosted_machine_authorization, "open_browser", lambda _: BROWSER_OPENED
    )

    def fail_complete(_pending, **_kwargs) -> None:
        raise hosted_machine_authorization.HostedMachineAuthorizationError(
            "approval expired"
        )

    monkeypatch.setattr(hosted_machine_authorization, "complete", fail_complete)
    app, _spy = make_app(WizardDefaults(config_path="/tmp/cfg.json", env_name="prod"))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("up", "enter")
            await app.workers.wait_for_complete()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            body = _body_text(app)
            assert "start a fresh browser sign-in" in body
            assert "paste a different token" not in body

    asyncio.run(scenario())
