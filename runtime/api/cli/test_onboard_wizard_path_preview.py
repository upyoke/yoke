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
from yoke_cli.config.onboard_wizard_widgets import (  # noqa: E402
    STEP_INSTALL,
    SelectionList,
    Stepper,
)


@pytest.fixture
def stub_path(monkeypatch):
    """Install a needs-fix diagnosis and refuse writes before Review."""
    monkeypatch.setattr(path_doctor, "diagnose", lambda **_: _diagnosis(needs_fix=True))
    monkeypatch.setattr(
        path_doctor,
        "apply_fix",
        lambda *_args, **_kwargs: pytest.fail("PATH was written before Review Apply"),
    )


def test_preview_queues_exact_managed_block_for_review(stub_path) -> None:
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
            await pilot.press("enter")  # preview: add the writes to Review
            await pilot.pause()

    asyncio.run(scenario())
    assert app.result.path_repair["targets"] == [
        {"surface": "login", "path": "/home/u/.zprofile"},
        {"surface": "ssh", "path": "/home/u/.zshenv"},
    ]


def test_preview_keeps_the_exact_block_behind_a_details_toggle(stub_path) -> None:
    from yoke_cli.config.path_state_contract import MANAGED_BEGIN, MANAGED_END

    app = _app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("space")  # Add-PATH -> review the writes now
            await pilot.pause()
            text = _visible_static_text(app)
            # Summary first: the markers are named, the block itself is folded.
            assert MANAGED_BEGIN in text
            assert "unset _yoke_managed_path" not in text
            assert "Show details" in text
            await pilot.press("down")  # Apply -> Show details
            await pilot.press("enter")
            await pilot.pause()
            text = _visible_static_text(app)
            assert "unset _yoke_managed_path" in text
            assert text.index(MANAGED_BEGIN) < text.index(MANAGED_END)
            assert "Hide details" in text
            assert app.query_one(SelectionList).selected_value == "details"
            await pilot.press("enter")  # Hide details
            await pilot.pause()
            text = _visible_static_text(app)
            assert "unset _yoke_managed_path" not in text
            assert app.query_one(SelectionList).selected_value == "details"
            assert app.query_one(Stepper).active == STEP_INSTALL

    asyncio.run(scenario())
