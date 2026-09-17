"""The PATH preview leads with what each shell file does; the block is a toggle away."""

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


def test_preview_shows_exact_managed_block_before_immediate_repair(stub_path) -> None:
    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")  # path diagnosis: "Show the exact change first"
            await pilot.press("enter")  # -> preview + consent
            await pilot.pause()
            # Plan lines wrap at the window edge; compare the words, not the rows.
            text = " ".join(_visible_static_text(app).split())
            assert (
                "Write /home/u/.zprofile: prepend /home/u/.local/bin (uv, uvx, yoke) "
                "to PATH for login shells." in text
            )
            assert (
                "Write /home/u/.zshenv: prepend /home/u/.local/bin (uv, uvx, yoke) to "
                "PATH for SSH and non-login shells, which never read "
                "/home/u/.zprofile." in text
            )
            assert "delete the block to undo" in text
            await pilot.press("enter")  # preview: write, verify, and continue
            await pilot.pause()

    asyncio.run(scenario())
    assert app.result.path_repair["targets"] == [
        {"surface": "login", "path": "/home/u/.zprofile"},
        {"surface": "ssh", "path": "/home/u/.zshenv"},
    ]


def test_preview_keeps_the_exact_block_visible_with_apply_and_back(stub_path) -> None:
    from yoke_cli.config.path_state_contract import MANAGED_BEGIN, MANAGED_END

    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")  # See exactly what changes
            await pilot.press("enter")
            await pilot.pause()
            text = _visible_static_text(app)
            assert MANAGED_BEGIN in text
            assert "unset _yoke_managed_path" in text
            assert text.index(MANAGED_BEGIN) < text.index(MANAGED_END)
            assert "Add to PATH and continue" in text
            assert "Back" in text

    asyncio.run(scenario())
