"""The PATH preview names the uv shell setup command."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from runtime.api.cli.test_yoke_operations_cli_onboard_wizard_path import (  # noqa: E402
    _app,
    _diagnosis,
    _visible_static_text,
)
from yoke_cli.config import path_doctor  # noqa: E402


@pytest.fixture
def stub_path(monkeypatch):
    """Install a needs-fix diagnosis and a successful immediate repair."""
    monkeypatch.setattr(path_doctor, "diagnose", lambda **_: _diagnosis(needs_fix=True))

    def apply(plan, *, progress, report):
        del progress
        report["path_repair"] = {
            **plan,
            "login_verified": True,
            "ssh_verified": True,
        }

    monkeypatch.setattr("yoke_cli.config.onboard_apply_path.apply", apply)


def test_preview_shows_uv_shell_setup_before_immediate_repair(stub_path) -> None:
    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")  # path diagnosis: "Show the exact change first"
            await pilot.press("enter")  # -> preview + consent
            await pilot.pause()
            # Plan lines wrap at the window edge; compare the words, not the rows.
            text = " ".join(_visible_static_text(app).split())
            assert "uv tool update-shell" in text
            assert "uv selects the shell files" in text
            await pilot.press("enter")  # preview: write, verify, and continue
            await pilot.pause()

    asyncio.run(scenario())
    assert app.result.path_repair["targets"] == [
        {"surface": "shell", "path": "uv tool update-shell"},
    ]


def test_preview_keeps_uv_command_visible_with_apply_and_back(stub_path) -> None:

    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")  # See exactly what changes
            await pilot.press("enter")
            await pilot.pause()
            text = _visible_static_text(app)
            assert "uv tool update-shell" in text
            assert "Add to PATH and continue" in text
            assert "Back" in text

    asyncio.run(scenario())
