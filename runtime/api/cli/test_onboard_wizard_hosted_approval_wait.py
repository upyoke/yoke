"""The browser-approval wait can be left, and it says why no browser opened.

Esc during the hosted poll abandons the wait and returns to the destination
picker; the pending one-time code simply expires server-side. Every approval
view carries the complete URL (the one with the code) and one line saying the
browser opened or why it did not, and that reason also lands in the wizard's
diagnostic log.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

pytest.importorskip("textual")

from yoke_cli.config import hosted_machine_authorization  # noqa: E402
from yoke_cli.config import onboard_wizard_diagnostics  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402
from yoke_cli.config.onboard_wizard_widgets import Stepper  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
)

COMPLETE_URL = "https://app.upyoke.com/connect?user_code=ABCD-2345"
FAILURE_REASON = "webbrowser.open returned False"


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def _body_text(app) -> str:
    from textual.widgets import Static

    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


def _pending(url: str) -> hosted_machine_authorization.PendingMachineAuthorization:
    return hosted_machine_authorization.PendingMachineAuthorization(
        platform_url=url,
        device_code="device-secret",
        user_code="ABCD-2345",
        verification_uri=f"{url}/connect",
        verification_uri_complete=f"{url}/connect?user_code=ABCD-2345",
        expires_in=600,
        interval=1,
    )


def _stub_start(monkeypatch, *, opened: bool) -> None:
    monkeypatch.setattr(hosted_machine_authorization, "start", _pending)
    result = (
        hosted_machine_authorization.BrowserOpenResult(opened=True, method="webbrowser")
        if opened
        else hosted_machine_authorization.BrowserOpenResult(
            opened=False, reason=FAILURE_REASON,
        )
    )
    monkeypatch.setattr(hosted_machine_authorization, "open_browser", lambda _p: result)


def _stub_blocking_poll(monkeypatch) -> dict:
    """A poll that only ends when the wizard cancels it (or the test releases it)."""
    seen: dict = {"cancelled": False, "released": threading.Event()}

    def _complete(pending, *, sleep, cancelled, **_kwargs):
        while not seen["released"].is_set():
            sleep(0.05)
            if cancelled():
                seen["cancelled"] = True
                raise hosted_machine_authorization.HostedMachineAuthorizationCancelled(
                    "cancelled"
                )
        return hosted_machine_authorization.HostedMachineCredential(
            api_url="https://app.upyoke.com/api/orgs/acme", org="acme", token="t",
        )

    monkeypatch.setattr(hosted_machine_authorization, "complete", _complete)
    return seen


def _app(tmp_path):
    return make_app(WizardDefaults(
        config_path=str(tmp_path / "cfg.json"), env_name=None, api_url=None, token=None,
    ))


def test_escape_during_the_approval_wait_returns_to_the_picker(monkeypatch, tmp_path):
    _stub_start(monkeypatch, opened=True)
    seen = _stub_blocking_poll(monkeypatch)
    app, _spy = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("up", "up")  # wrap local -> stage -> upyoke.com
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "Sign in and choose an organization." in _body_text(app)
            await pilot.press("enter")  # Continue -> the waiting view
            await pilot.pause()
            assert app._checking
            assert "Waiting for browser approval." in _body_text(app)
            assert "esc" in _body_text(app)
            await pilot.press("escape")
            await pilot.pause()
            assert not app._checking
            assert "Where should this Yoke live?" in _body_text(app)
            assert app.query_one(Stepper).account_label == "Account"
            assert app._hosted_machine_authorization is None
            await app.workers.wait_for_complete()
            await pilot.pause()
            # The abandoned worker ended on the cancel signal and its result
            # never routed anywhere: the picker is still up.
            assert seen["cancelled"]
            assert "Where should this Yoke live?" in _body_text(app)

    asyncio.run(scenario())
    log = onboard_wizard_diagnostics.log_path(tmp_path / "cfg.json").read_text()
    assert "browser-approval-cancelled" in log


def test_every_approval_view_names_the_complete_url_and_the_browser_outcome(
    monkeypatch, tmp_path,
):
    _stub_start(monkeypatch, opened=False)
    seen = _stub_blocking_poll(monkeypatch)
    app, _spy = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("up", "up")
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            first = _body_text(app)
            assert f"Open: {COMPLETE_URL}" in first
            assert f"The browser did not open ({FAILURE_REASON})" in first
            assert "onboard-wizard.log" in first
            await pilot.press("enter")
            await pilot.pause()
            waiting = _body_text(app)
            assert f"Open: {COMPLETE_URL}" in waiting
            assert "One-time code: ABCD-2345" in waiting
            assert f"The browser did not open ({FAILURE_REASON})" in waiting
            seen["released"].set()
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(scenario())
    log = onboard_wizard_diagnostics.log_path(tmp_path / "cfg.json").read_text()
    assert "browser-open" in log
    assert "opened=False" in log
    assert FAILURE_REASON in log


def test_a_browser_that_opened_says_so_on_the_waiting_view(monkeypatch, tmp_path):
    _stub_start(monkeypatch, opened=True)
    seen = _stub_blocking_poll(monkeypatch)
    app, _spy = _app(tmp_path)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("up", "up")
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert "The browser was opened for you." in _body_text(app)
            seen["released"].set()
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(scenario())
    log = onboard_wizard_diagnostics.log_path(tmp_path / "cfg.json").read_text()
    assert "opened=True method=webbrowser" in log


def test_escape_from_a_preset_hosted_run_steps_back_without_a_picker(
    monkeypatch, tmp_path,
):
    _stub_start(monkeypatch, opened=True)
    _stub_blocking_poll(monkeypatch)
    app, _spy = make_app(WizardDefaults(
        config_path=str(tmp_path / "cfg.json"),
        destination="hosted",
        env_name="prod",
        api_url="https://app.upyoke.com",
        token=None,
    ))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app._checking
            await pilot.press("escape")
            await pilot.pause()
            assert not app._checking
            # No picker was ever shown on this run, so leaving the wait opens
            # one rather than re-entering the preset lane.
            assert "Where should this Yoke live?" in _body_text(app)

    asyncio.run(scenario())
