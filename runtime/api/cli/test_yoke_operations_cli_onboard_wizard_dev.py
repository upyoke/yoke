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
from pathlib import Path

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_dev as dev_flow  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config import yoke_dev_access as dev_access  # noqa: E402
from yoke_cli.config import yoke_dev_detect as dev_detect  # noqa: E402
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
    await type_text(pilot, "ghp_machinepat")
    await pilot.press("enter")
    await pilot.press("enter")  # GitHub verification success: Continue
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
    """A PAT that can't read Yoke's repo shows the 'you need both' error."""
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


def test_no_machine_pat_prompts_then_runs_github_check(monkeypatch) -> None:
    """Without a connected PAT the dev flow prompts for one before the repo check."""
    _stub_access(monkeypatch)
    _stub_detect(monkeypatch, [Path("/home/dev/yoke")])
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")   # machine github: Skip for now (no PAT)
            await pilot.press("enter")
            index = next(
                i for i, r in enumerate(steps.MODE_ROWS)
                if r.value == onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN
            )
            for _ in range(index):
                await pilot.press("down")
            await pilot.press("enter")  # Develop Yoke itself
            await pilot.pause()
            # Yoke-project check passed; now the PAT input is showing.
            from textual.widgets import Input
            inputs = list(app.query("#onboard-body Input").results(Input))
            assert inputs, "missing PAT prompt before the GitHub repo check"
            await type_text(pilot, "ghp_devpat")
            await pilot.press("enter")  # runs github check -> detect -> finish
            await pilot.pause()
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert app.result.machine_github_token == "ghp_devpat"
    assert applied["project_mode"] == onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN


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
