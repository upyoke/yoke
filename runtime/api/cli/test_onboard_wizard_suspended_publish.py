"""Publishing fallback for a suspended GitHub App installation."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from runtime.api.cli.onboard_wizard_test_helpers import make_app  # noqa: E402
from runtime.api.cli.test_yoke_operations_cli_onboard_wizard_publish_capability import (  # noqa: E402
    _body_text,
    _github_config,
    _mark_connected,
)
from yoke_cli.config import machine_config  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_publish as publish_flow  # noqa: E402
from yoke_cli.config import onboard_wizard_project_screens as screens  # noqa: E402
from yoke_contracts import github_origin  # noqa: E402


def test_suspended_administration_installation_never_opens_empty_owner_picker(
    monkeypatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        machine_config,
        "github_config",
        lambda _path: _github_config(
            administration=True,
            suspended=True,
        ),
    )
    monkeypatch.setattr(publish_flow.webbrowser, "open", opened.append)
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            _mark_connected(app)
            app.result.project_checkout = "/home/code/widget"
            app._on_publish_choice(screens.PUBLISH_YES)
            await pilot.pause()
            assert "Administration permission" in _body_text(app)
            await pilot.press("down")
            await pilot.press("enter")

    asyncio.run(scenario())

    assert opened == [f"{github_origin.DEFAULT_GITHUB_WEB_URL}/new"]
    assert app.result.project_publish_to_github is False
    assert not getattr(app, "_owner_lookup", {})
