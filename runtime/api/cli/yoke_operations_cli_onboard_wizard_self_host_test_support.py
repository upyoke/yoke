# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.cli.yoke_operations_cli_onboard_wizard_publish_capability_test_support import _body_text as _body_text

import asyncio

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_docker_prerequisites as docker  # noqa: E402

from yoke_cli.config import onboard_self_host_server as server  # noqa: E402

from yoke_cli.config import yoke_token_verify  # noqa: E402

from yoke_cli.config.onboard_destinations import DESTINATION_SERVER  # noqa: E402

from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402

from yoke_cli.config import onboard_wizard_self_host as flow  # noqa: E402

from yoke_cli.config import onboard_wizard_flow_connect as connect_flow  # noqa: E402

from yoke_cli.config.onboard_wizard_widgets import (  # noqa: E402
    STEP_GITHUB,
    SelectionList,
    Stepper,
)

from yoke_cli.self_host import first_boot_token  # noqa: E402

from yoke_contracts.self_host_bootstrap_output import (  # noqa: E402
    TOKEN_BODY_LENGTH,
    TOKEN_PREFIX,
)

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
    type_text,
)


async def _wait_for_text(app, pilot, expected: str) -> str:
    for _ in range(20):
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = _body_text(app)
        if expected in text:
            return text
    return _body_text(app)


def _app(tmp_path):
    return make_app(WizardDefaults(config_path=str(tmp_path / "config.json")))


async def _open_preview(pilot) -> None:
    await advance_past_path(pilot)
    await pilot.press("down", "down", "enter")


async def _start(pilot) -> None:
    """Start, then answer the first-admin name prompt it opens."""
    await _open_preview(pilot)
    await pilot.press("enter", "enter")  # Preview -> Start fresh
    await type_text(pilot, "Ada Lovelace")
    await pilot.press("enter")
