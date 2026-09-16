"""Wizard coverage for the public ``Edit Yoke source`` persona."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_dev as dev_flow  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config import yoke_dev_detect as dev_detect  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402
from yoke_cli.config.onboard_wizard_widgets import SelectionList  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
    type_text,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def _stub_detect(monkeypatch, checkouts, *, accept=True):
    monkeypatch.setattr(dev_detect, "detect_yoke_checkouts", lambda: list(checkouts))
    if accept:
        monkeypatch.setattr(
            dev_detect, "preflight_dev_checkout", lambda *_a, **_k: None
        )


async def _pick_edit_yoke(pilot) -> None:
    await advance_past_path(pilot)
    await pilot.press("down")  # GitHub: Skip for now
    await pilot.press("enter")
    index = next(
        i
        for i, row in enumerate(steps.MODE_ROWS)
        if row.value == onboard_project.PROJECT_MODE_EDIT_YOKE_SOURCE
    )
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")


def _body_text(app) -> str:
    from textual.widgets import Static

    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


def test_single_checkout_needs_no_github_or_official_project_access(
    monkeypatch,
) -> None:
    _stub_detect(monkeypatch, [Path("/home/dev/forked-yoke")])
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _pick_edit_yoke(pilot)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(scenario())
    applied = spy.applied
    assert applied is not None
    assert applied["machine_github_choice"] == "skip"
    assert applied["project_mode"] == onboard_project.PROJECT_MODE_EDIT_YOKE_SOURCE
    assert applied["project_checkout"] == "/home/dev/forked-yoke"
    assert applied["project_slug"] is None
    assert applied["project_public_item_prefix"] is None


def test_project_mode_preset_uses_selected_checkout(monkeypatch) -> None:
    checkout = "/src/my-yoke-fork"
    monkeypatch.setattr(
        dev_detect,
        "detect_yoke_checkouts",
        lambda: (_ for _ in ()).throw(AssertionError("preset should bypass detection")),
    )
    monkeypatch.setattr(dev_detect, "preflight_dev_checkout", lambda *_a, **_k: None)
    app, spy = make_app(
        WizardDefaults(
            config_path="/tmp/cfg.json",
            env_name="prod",
            api_url="https://api.test",
            token="actor-token",
            project_mode=onboard_project.PROJECT_MODE_EDIT_YOKE_SOURCE,
            project_checkout=checkout,
        )
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(scenario())
    assert spy.applied is not None
    assert spy.applied["project_checkout"] == checkout


def test_multiple_checkouts_show_each_path_and_clone_option(monkeypatch) -> None:
    _stub_detect(monkeypatch, [Path("/home/dev/yoke"), Path("/srv/my-yoke")])
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _pick_edit_yoke(pilot)
            await pilot.pause()
            selection = app.query_one("#onboard-body SelectionList", SelectionList)
            values = [row.value for row in selection.rows]
            assert "/home/dev/yoke" in values
            assert "/srv/my-yoke" in values
            assert dev_flow._CLONE_SOURCE in values
            assert "No official Yoke access is required" in _body_text(app)

    asyncio.run(scenario())


def test_clone_accepts_user_supplied_fork_and_target(monkeypatch) -> None:
    _stub_detect(monkeypatch, [])
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _pick_edit_yoke(pilot)
            await pilot.pause()
            await pilot.press("down")  # Clone Yoke source
            await pilot.press("enter")
            await type_text(pilot, "https://github.com/example/my-yoke.git")
            await pilot.press("enter")
            await type_text(pilot, "/home/me/my-yoke")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(scenario())
    assert spy.applied is not None
    assert spy.applied["project_remote_url"] == "https://github.com/example/my-yoke.git"
    assert spy.applied["project_checkout"] == "/home/me/my-yoke"


def test_non_yoke_folder_shows_cause_and_required_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _stub_detect(monkeypatch, [], accept=False)
    conflict = tmp_path / "not-yoke"
    conflict.mkdir()
    (conflict / "README.md").write_text("not yoke\n", encoding="utf-8")
    app, spy = make_app()
    captured = ""

    async def scenario() -> None:
        nonlocal captured
        async with app.run_test() as pilot:
            await _pick_edit_yoke(pilot)
            await pilot.pause()
            await pilot.press("enter")  # Choose another checkout
            await type_text(pilot, str(conflict))
            await pilot.press("enter")
            await pilot.pause()
            captured = _body_text(app)

    asyncio.run(scenario())
    assert spy.applied is None
    assert "not a Yoke source checkout" in captured
    assert "Choose an existing Yoke source checkout" in captured
