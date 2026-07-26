"""Pilot coverage for the picker's two hosted rows.

`upyoke.com` and `stage.upyoke.com` are one destination reached through two
platforms: the row picked is what the browser connect leg opens, and no second
screen asks which hosted environment to use. Split from the destination-picker
pilot suite, which covers the local and team-server lanes.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_cli.config import hosted_machine_authorization  # noqa: E402
from yoke_cli.config import local_universe_setup  # noqa: E402
from yoke_cli.config.onboard_destinations import DESTINATION_HOSTED  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402
from yoke_cli.config.onboard_wizard_widgets import (  # noqa: E402
    STEP_CONNECT_LABEL,
    SelectionList,
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


def _picker_defaults(**overrides) -> WizardDefaults:
    kwargs = dict(config_path="/tmp/cfg.json", env_name=None, api_url=None)
    kwargs.update(overrides)
    return WizardDefaults(**kwargs)


def _stub_browser_approval(monkeypatch) -> list[str]:
    """Capture the platform a hosted row hands the connect leg."""
    started: list[str] = []

    def _start(url: str):
        started.append(url)
        return hosted_machine_authorization.PendingMachineAuthorization(
            platform_url=url,
            device_code="device-secret",
            user_code="ABCD-2345",
            verification_uri=f"{url}/machine",
            verification_uri_complete=f"{url}/machine?code=ABCD-2345",
            expires_in=600,
            interval=1,
        )

    monkeypatch.setattr(hosted_machine_authorization, "start", _start)
    monkeypatch.setattr(hosted_machine_authorization, "open_browser", lambda _: False)
    return started

def test_the_picker_carries_the_hosted_environment_choice(monkeypatch) -> None:
    started = _stub_browser_approval(monkeypatch)
    app, _spy = make_app(_picker_defaults(token=None))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            rows = app.query_one(SelectionList).rows
            # Both platforms are rows of the one question; there is no second
            # screen asking which hosted environment to use.
            assert [row.label for row in rows] == [
                "This machine",
                "A team server",
                "upyoke.com",
                "stage.upyoke.com",
            ]
            await pilot.press("up", "up")  # wrap local -> stage -> upyoke.com
            await pilot.press("enter")
            # No second question: the pick handed the connect leg a platform.
            assert "Which hosted environment" not in _body_text(app)
            assert started == ["https://app.upyoke.com"]
            assert app.result.destination == DESTINATION_HOSTED
            assert app.result.env_name == "prod"

    asyncio.run(scenario())


def test_the_staging_row_points_the_connect_leg_at_stage(monkeypatch) -> None:
    started = _stub_browser_approval(monkeypatch)
    app, _spy = make_app(_picker_defaults(token=None))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("up")  # wrap local -> stage.upyoke.com
            await pilot.press("enter")
            # The staging row is the same hosted destination reached through
            # the other platform, not a fourth kind of home.
            assert app.result.destination == DESTINATION_HOSTED
            assert app.result.env_name == "stage"
            assert started == ["https://app.stage.upyoke.com"]

    asyncio.run(scenario())


def test_back_from_local_summary_repicks_cleanly(monkeypatch) -> None:
    _stub_browser_approval(monkeypatch)
    app, _spy = make_app(_picker_defaults(token=None))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")
            await pilot.press("escape")  # back to the picker
            await pilot.pause()
            assert "Where should this Yoke live?" in _body_text(app)
            assert app.query_one(Stepper).account_label == STEP_CONNECT_LABEL
            await pilot.press("up", "up")  # repick: wrap local -> upyoke.com
            await pilot.press("enter")
            await pilot.pause()
            # The local detour left no residue: the hosted row sets its own
            # environment and goes straight to browser approval.
            assert app.result.env_name != local_universe_setup.LOCAL_ENV
            assert "Which hosted environment" not in _body_text(app)

    asyncio.run(scenario())
