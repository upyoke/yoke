# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import asyncio

import threading

import pytest

pytest.importorskip("textual")

from textual.widgets import Input, Static  # noqa: E402

from yoke_cli.config import onboard_project  # noqa: E402

from yoke_cli.config import onboard_wizard_flow  # noqa: E402

from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402

from yoke_cli.config import project_git_probe  # noqa: E402

from yoke_cli.config import project_git_transport  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
    type_text,
)


def _title(app) -> str:
    return next(str(w.render()) for w in app.query(".onboard-title").results(Static))


def _error_text(app) -> str:
    return " ".join(
        str(w.render())
        for selector in (".onboard-input-error", ".onboard-field-error")
        for w in app.query(selector).results(Static)
    )


async def _pick_mode(pilot, value: str) -> None:
    index = next(i for i, r in enumerate(steps.MODE_ROWS) if r.value == value)
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")


async def _skip_machine_github(pilot) -> None:
    await advance_past_path(pilot)
    await pilot.press("down")  # machine github: Skip for now
    await pilot.press("enter")
