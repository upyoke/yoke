"""Pilot coverage for the wizard's deployment-destination picker.

The Account step opens on one picker — this machine / a team server /
upyoke.com — and the answer changes only the sign-in lane: local swaps
sign-in for the universe summary (birth runs at Apply), server collects a
URL then a token, hosted keeps the environment select. The closing test
drives the real apply seam end to end (picker → local → Apply) against a
scratch machine home with the embedded-Postgres engine stubbed, and proves
the written config matches what ``yoke init --local`` lands.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("textual")

from yoke_cli import main as yoke_operations_cli  # noqa: E402
from yoke_cli.commands.adapters import onboard_apply  # noqa: E402
from yoke_cli.config import local_universe_setup  # noqa: E402
from yoke_cli.config.onboard_destinations import (  # noqa: E402
    DESTINATION_HOSTED,
    DESTINATION_LOCAL,
    DESTINATION_SERVER,
)
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp  # noqa: E402
from yoke_cli.config.onboard_wizard_flow_destination import (  # noqa: E402
    ACCOUNT_STEP_LABELS,
)
from yoke_cli.config.onboard_wizard_widgets import (  # noqa: E402
    STEP_CONNECT_LABEL,
    STEP_GITHUB,
    SelectionList,
    Stepper,
)

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
    type_text,
)
from runtime.api.cli.test_yoke_operations_cli_onboard_destination import (  # noqa: E402
    FAKE_DSN,
    _FakeEngine,
    _normalized_local_connection,
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


async def _wait_for_body_text(app, pilot, expected: str) -> str:
    for _ in range(20):
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = _body_text(app)
        if expected in text:
            return text
    return _body_text(app)


def _picker_defaults(**overrides) -> WizardDefaults:
    kwargs = dict(config_path="/tmp/cfg.json", env_name=None, api_url=None)
    kwargs.update(overrides)
    return WizardDefaults(**kwargs)


def test_picker_opens_account_step_with_hosted_preselected() -> None:
    app, _spy = make_app(_picker_defaults())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            text = _body_text(app)
            assert "Where should this Yoke live?" in text
            assert app.query_one(SelectionList).selected_value == (
                DESTINATION_HOSTED
            )

    asyncio.run(scenario())


def test_local_pick_swaps_sign_in_for_universe_summary() -> None:
    app, _spy = make_app(_picker_defaults(token="stale-token"))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")   # picker: wrap hosted -> This machine
            await pilot.press("enter")
            text = _body_text(app)
            assert "Your Yoke lives on this machine." in text
            assert app.result.destination == DESTINATION_LOCAL
            assert app.result.env_name == local_universe_setup.LOCAL_ENV
            assert app.result.api_url == ""
            assert app.result.token is None  # local lane clears sign-in state
            stepper = app.query_one(Stepper)
            assert stepper.account_label == (
                ACCOUNT_STEP_LABELS[DESTINATION_LOCAL]
            )
            await pilot.press("enter")  # summary: Continue -> GitHub step
            await pilot.pause()
            assert stepper.active == STEP_GITHUB

    asyncio.run(scenario())


def test_server_pick_collects_url_then_token() -> None:
    app, _spy = make_app(_picker_defaults(token=None))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("up")     # picker: hosted -> A team server
            await pilot.press("enter")
            assert "Enter your Yoke server URL." in _body_text(app)
            await type_text(pilot, "https://yoke.acme.test")
            await pilot.press("enter")
            await pilot.pause()
            assert app.result.destination == DESTINATION_SERVER
            assert app.result.api_url == "https://yoke.acme.test"
            assert "Provide your Yoke API token." in _body_text(app)

    asyncio.run(scenario())


def test_hosted_pick_shows_hosted_environments_only() -> None:
    app, _spy = make_app(_picker_defaults(token=None))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")  # picker: upyoke.com (default)
            text = _body_text(app)
            assert "Which hosted environment should this machine use?" in text
            rows = app.query_one(SelectionList).rows
            assert [row.label for row in rows] == ["Production", "Stage"]
            assert app.result.destination == DESTINATION_HOSTED

    asyncio.run(scenario())


def test_preset_destination_skips_picker() -> None:
    app, _spy = make_app(_picker_defaults(destination=DESTINATION_LOCAL))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            text = _body_text(app)
            assert "Your Yoke lives on this machine." in text
            assert "Where should this Yoke live?" not in text

    asyncio.run(scenario())


def test_back_from_local_summary_repicks_cleanly() -> None:
    app, _spy = make_app(_picker_defaults(token=None))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")   # picker -> This machine
            await pilot.press("enter")
            await pilot.press("escape")  # back to the picker
            await pilot.pause()
            assert "Where should this Yoke live?" in _body_text(app)
            assert app.query_one(Stepper).account_label == STEP_CONNECT_LABEL
            await pilot.press("enter")  # repick: upyoke.com default
            await pilot.pause()
            # The local detour left no residue: hosted collects env + token.
            assert app.result.env_name != local_universe_setup.LOCAL_ENV
            assert "Which hosted environment" in _body_text(app)

    asyncio.run(scenario())


def test_local_flow_applies_local_destination_field_set() -> None:
    app, spy = make_app(_picker_defaults())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")   # picker -> This machine
            await pilot.press("enter")
            await pilot.press("enter")  # universe summary: Continue
            await pilot.press("down")   # github: Skip for now
            await pilot.press("enter")
            for _ in range(4):          # project: machine-only
                await pilot.press("down")
            await pilot.press("enter")
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["destination"] == DESTINATION_LOCAL
    assert applied["env_name"] == local_universe_setup.LOCAL_ENV
    assert applied["api_url"] == ""
    assert applied["token"] is None


def test_wizard_local_apply_lands_config_like_yoke_init_local(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Drive picker → local → Apply against the REAL apply seam.

    The embedded-Postgres engine is stubbed at the birth seam; everything
    else (report assembly, machine-config writes, apply report) is real and
    lands under a scratch machine home, then is compared with what
    ``yoke init --local`` writes with the same engine stub.
    """
    monkeypatch.setattr(
        local_universe_setup, "_engine", lambda: _FakeEngine(),
    )
    wizard_home = tmp_path / "wizard-home"
    init_home = tmp_path / "init-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(wizard_home))

    app = OnboardWizardApp(
        defaults=WizardDefaults(
            config_path=str(wizard_home / "config.json"),
        ),
        apply_report=onboard_apply.apply_with_durable_report,
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")  # PATH all clear: continue
            await pilot.press("down")   # picker -> This machine
            await pilot.press("enter")
            await pilot.press("enter")  # universe summary: Continue
            await pilot.press("down")   # github: Skip for now
            await pilot.press("enter")
            for _ in range(4):          # project: machine-only
                await pilot.press("down")
            await pilot.press("enter")
            await _wait_for_body_text(app, pilot, "Review what")
            await pilot.press("enter")  # review: Apply
            text = await _wait_for_body_text(app, pilot, "Setup complete.")
            assert "Setup complete." in text

    asyncio.run(scenario())

    wizard_config = json.loads(
        (wizard_home / "config.json").read_text(encoding="utf-8")
    )
    assert wizard_config["active_env"] == local_universe_setup.LOCAL_ENV

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(init_home))
    assert yoke_operations_cli.main(["init", "--local", "--json"]) == 0
    capsys.readouterr()

    assert (
        _normalized_local_connection(wizard_home)
        == _normalized_local_connection(init_home)
    )
    assert _normalized_local_connection(wizard_home)["dsn_value"] == FAKE_DSN
