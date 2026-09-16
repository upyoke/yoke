"""Inline validation for the branch and item prefix in Project details."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Input  # noqa: E402

from yoke_cli.config import onboard_project  # noqa: E402
from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    make_app,
    stub_path_doctor,
    type_text,
)
from runtime.api.cli.test_yoke_operations_cli_onboard_wizard_inline_validation import (  # noqa: E402
    _error_text,
    _pick_mode,
    _skip_machine_github,
    _title,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


@pytest.mark.parametrize(
    ("field_id", "value", "enters"),
    [
        ("onboard-input-branch", "bad branch", 2),
        ("onboard-input-prefix", "TOOLONG", 3),
    ],
)
def test_invalid_project_detail_stays_on_the_form(
    field_id: str,
    value: str,
    enters: int,
) -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
            await type_text(pilot, "/home/code/widget")
            await pilot.press("enter")
            for _ in range(enters):
                await pilot.press("enter")
            field = app.query_one(f"#{field_id}", Input)
            field.value = ""
            await type_text(pilot, value)
            await pilot.press("enter")
            await pilot.pause()
            assert _title(app) == "Project details."
            assert _error_text(app).strip()

    asyncio.run(scenario())
