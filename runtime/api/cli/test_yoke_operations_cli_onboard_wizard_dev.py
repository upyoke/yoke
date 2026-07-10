"""Wizard coverage for the 'Develop Yoke itself' source-dev-admin flow.

Selecting 'Develop Yoke itself' runs two access checks (Yoke-project access,
GitHub-repo access) then existing-checkout detection. ``build_report`` is spied
at the wizard boundary and every network/detection seam is stubbed, so no
scenario hits the Yoke API, GitHub, or the filesystem. Each failed check
renders the recoverable error screen; the all-pass path reaches a clean Finish
as source-dev-admin.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_dev as dev_flow  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config import yoke_dev_access as dev_access  # noqa: E402
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


def _stub_access(monkeypatch, *, yoke_ok=True, github_ok=True):
    monkeypatch.setattr(
        dev_flow.github_state, "user_access_token", lambda _result: "ghu_short_lived",
    )
    monkeypatch.setattr(
        dev_access, "yoke_project_reachable", lambda api_url, token: yoke_ok,
    )
    monkeypatch.setattr(
        dev_access, "github_can_reach_yoke_repo",
        lambda api_url, token: github_ok,
    )


def _stub_detect(monkeypatch, checkouts):
    monkeypatch.setattr(
        dev_detect, "detect_yoke_checkouts", lambda: list(checkouts),
    )


async def _pick_develop_yoke(pilot) -> None:
    await advance_past_path(pilot)
    await pilot.press("enter")  # machine github: Connect (default)
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()
    index = next(
        i for i, r in enumerate(steps.MODE_ROWS)
        if r.value == onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN
    )
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")  # select Develop Yoke itself


def _error_text(app) -> str:
    """Join the rendered body Static lines.

    Must be called while the app is still running (inside ``run_test``): Textual
    tears the body DOM down on app shutdown, so a query after ``asyncio.run``
    returns sees no widgets at all.
    """
    from textual.widgets import Static

    lines = [
        str(w.render())
        for w in app.query("#onboard-body Static").results(Static)
    ]
    return " ".join(lines)


def test_all_pass_single_checkout_reaches_clean_finish(monkeypatch) -> None:
    """All checks pass + one detected checkout -> source-dev-admin Finish apply."""
    _stub_access(monkeypatch)
    _stub_detect(monkeypatch, [Path("/home/dev/yoke")])
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _pick_develop_yoke(pilot)
            await pilot.pause()
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["project_mode"] == onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN
    assert applied["project_checkout"] == "/home/dev/yoke"
    assert applied["project_slug"] == dev_access.YOKE_PROJECT_SLUG
    assert applied["project_default_branch"] == "main"
    assert applied["project_public_item_prefix"] == "YOK"


def test_stored_yoke_checkout_offers_direct_source_dev_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    yoke_checkout = tmp_path / "yoke"
    (yoke_checkout / "runtime" / "harness").mkdir(parents=True)
    (yoke_checkout / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n',
        encoding="utf-8",
    )
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"projects": {str(yoke_checkout): {"project_id": 1}}}),
        encoding="utf-8",
    )
    _stub_access(monkeypatch)
    monkeypatch.setattr(
        dev_detect,
        "detect_yoke_checkouts",
        lambda: (_ for _ in ()).throw(AssertionError("preset checkout not used")),
    )
    app, spy = make_app(WizardDefaults(
        config_path=str(config),
        env_name="prod",
        api_url="https://api.test",
        token="actor-token",
    ))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")  # machine github: Connect (default)
            await app.workers.wait_for_complete()
            await pilot.pause()
            text = _error_text(app)
            assert "Use an existing project mapping?" in text
            assert "Develop Yoke itself" in text
            await pilot.press("down")   # direct source-dev row
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["project_mode"] == onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN
    assert applied["project_checkout"] == str(yoke_checkout)


def test_project_mode_default_forces_source_dev_checkout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    yoke_checkout = tmp_path / "yoke"
    (yoke_checkout / "runtime" / "harness").mkdir(parents=True)
    (yoke_checkout / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\n',
        encoding="utf-8",
    )
    _stub_access(monkeypatch)
    monkeypatch.setattr(
        dev_detect,
        "detect_yoke_checkouts",
        lambda: (_ for _ in ()).throw(AssertionError("preset checkout not used")),
    )
    app, spy = make_app(WizardDefaults(
        config_path=str(tmp_path / "config.json"),
        env_name="prod",
        api_url="https://api.test",
        token="actor-token",
        project_mode=onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN,
        project_checkout=str(yoke_checkout),
    ))

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")  # machine github: Connect (default)
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["project_mode"] == onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN
    assert applied["project_checkout"] == str(yoke_checkout)


def test_no_yoke_project_access_renders_error(monkeypatch) -> None:
    """A token that can't reach the Yoke project shows the project-access error."""
    _stub_access(monkeypatch, yoke_ok=False)
    app, _spy = make_app()
    captured: dict[str, str] = {}

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _pick_develop_yoke(pilot)
            await pilot.pause()
            captured["text"] = _error_text(app)

    asyncio.run(scenario())

    assert "can't reach the Yoke project" in captured["text"]


def test_not_connected_to_control_plane_renders_error(monkeypatch) -> None:
    """No Yoke token at all says the machine isn't connected to a control plane.

    Driven at the handler so the missing-credential branch is exercised directly
    without depending on the wizard ever having a way to reach Develop-Yoke
    with no Yoke token (the Connect step normally collects one first).
    """
    _stub_access(monkeypatch)
    app, _spy = make_app()
    captured: dict[str, str] = {}

    async def scenario() -> None:
        async with app.run_test() as pilot:
            app.result.token = None
            app.result.token_file = None
            app.result.project_mode = onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN
            app._start_dev_flow()
            await pilot.pause()  # flush the deferred error-body swap
            captured["text"] = _error_text(app)

    asyncio.run(scenario())

    assert "isn't connected to a Yoke control plane" in captured["text"]


def test_no_github_repo_access_renders_you_need_both_error(monkeypatch) -> None:
    """A GitHub App user token that can't read Yoke's repo shows the 'you need both' error."""
    _stub_access(monkeypatch, github_ok=False)
    app, _spy = make_app()
    captured: dict[str, str] = {}

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _pick_develop_yoke(pilot)
            await pilot.pause()
            captured["text"] = _error_text(app)

    asyncio.run(scenario())

    assert (
        "you need BOTH Yoke-project access and GitHub access".lower()
        in captured["text"].lower()
    )


def test_no_machine_github_app_access_blocks_source_dev(monkeypatch) -> None:
    """Source development requires an already connected App authorization."""
    _stub_access(monkeypatch)
    _stub_detect(monkeypatch, [Path("/home/dev/yoke")])
    app, _spy = make_app()
    captured: dict[str, str] = {}

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")
            await pilot.press("enter")
            index = next(
                i for i, row in enumerate(steps.MODE_ROWS)
                if row.value == onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN
            )
            for _ in range(index):
                await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            captured["text"] = _error_text(app)

    asyncio.run(scenario())

    assert "requires GitHub App access" in captured["text"]
    assert not hasattr(app.result, "machine_github_token")


def test_multiple_checkouts_render_picker_with_clone_option(monkeypatch) -> None:
    """Many detected checkouts show a picker including a clone-Yoke row."""
    _stub_access(monkeypatch)
    _stub_detect(monkeypatch, [Path("/home/dev/yoke"), Path("/srv/yoke")])
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _pick_develop_yoke(pilot)
            await pilot.pause()
            selection = app.query_one("#onboard-body SelectionList", SelectionList)
            values = [row.value for row in selection.rows]
            assert "/home/dev/yoke" in values
            assert "/srv/yoke" in values
            assert dev_flow._CLONE_YOKE in values

    asyncio.run(scenario())


def test_no_checkout_found_asks_where_then_finishes(monkeypatch) -> None:
    """No detected checkout asks where the checkout is, then finishes on the path."""
    _stub_access(monkeypatch)
    _stub_detect(monkeypatch, [])
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _pick_develop_yoke(pilot)
            await pilot.pause()
            from textual.widgets import Input
            inputs = list(app.query("#onboard-body Input").results(Input))
            assert inputs, "expected the 'where is your Yoke checkout?' input"
            await type_text(pilot, "/home/me/yoke")
            await pilot.press("enter")  # -> finish
            await pilot.pause()
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["project_checkout"] == "/home/me/yoke"
    assert applied["project_mode"] == onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN


def test_non_empty_non_yoke_folder_is_refused_before_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A conflicting folder gets a recoverable error before the Finish screen."""
    _stub_access(monkeypatch)
    _stub_detect(monkeypatch, [])
    conflict = tmp_path / "not-yoke"
    conflict.mkdir()
    (conflict / "README.md").write_text("not yoke\n", encoding="utf-8")
    app, spy = make_app()
    captured: dict[str, str] = {}

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _pick_develop_yoke(pilot)
            await pilot.pause()
            await type_text(pilot, str(conflict))
            await pilot.press("enter")
            await pilot.pause()
            captured["text"] = _error_text(app)

    asyncio.run(scenario())

    assert spy.applied is None
    assert "already has files" in captured["text"]
    assert "not a Yoke source checkout" in captured["text"]
    assert "Press esc to go back" in captured["text"]
