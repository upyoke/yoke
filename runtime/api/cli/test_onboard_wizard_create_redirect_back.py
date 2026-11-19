"""Create-new pointed at an existing folder adopts it, and Back undoes that."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

pytest.importorskip("textual")

from textual.widgets import Input  # noqa: E402

from yoke_cli.config import onboard_project, onboard_report  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config.onboard_wizard_plan_review import classify_plan  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
)
from runtime.api.cli.onboard_wizard_view_test_support import wait_for_view  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def _existing_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "existing"
    folder.mkdir()
    (folder / "README.md").write_text("code already here\n")
    return folder


async def _to_create_folder_prompt(pilot) -> None:
    await advance_past_path(pilot)
    await pilot.press("down")  # machine github: Skip for now
    await pilot.press("enter")
    await wait_for_view(pilot, "project.mode", "SelectionList")
    index = next(
        i
        for i, row in enumerate(steps.MODE_ROWS)
        if row.value == onboard_project.PROJECT_MODE_CREATE_REPO
    )
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")
    await wait_for_view(pilot, "project.folder", "Input")


async def _submit_folder(pilot, value: str) -> None:
    field = pilot.app.query_one("#onboard-input", Input)
    field.value = value
    field.cursor_position = len(value)
    await pilot.press("enter")
    await wait_for_view(pilot, "project.details", "#onboard-input-slug")


def _plan(app) -> dict:
    result = app.result
    return onboard_report.build_plan(
        Path("/home/.yoke/config.json"),
        "prod",
        "https://api.test",
        {"kind": "token_file", "path": "/home/.yoke/secrets/prod.token"},
        {"kind": "token_file", "path": "/home/.yoke/secrets/prod.token"},
        "quick",
        project_mode=result.project_mode,
        project_inputs={
            "mode": result.project_mode,
            "checkout": result.project_checkout,
            "slug": "widget",
            "name": "Widget",
            "github_adoption": "disabled",
        },
        machine_github={"choice": "skip"},
    )


def _review_lines(plan: dict) -> list[str]:
    return [
        line for lines in classify_plan({"plan": plan}).values() for line in lines
    ]


def _actions(plan: dict) -> list[str]:
    return [step["action"] for step in plan["steps"]]


def test_back_to_a_new_path_restores_create_new(tmp_path) -> None:
    app, _spy = make_app()
    existing = _existing_folder(tmp_path)
    fresh = tmp_path / "fresh-project"

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _to_create_folder_prompt(pilot)
            await _submit_folder(pilot, str(existing))
            assert app.result.project_mode == (
                onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
            )
            await pilot.press("escape")
            await wait_for_view(pilot, "project.folder", "Input")
            await _submit_folder(pilot, str(fresh))

    asyncio.run(scenario())

    assert app.result.project_mode == onboard_project.PROJECT_MODE_CREATE_REPO
    assert app.result.project_checkout == str(fresh)
    plan = _plan(app)
    assert "project-create-checkout" in _actions(plan)
    lines = " ".join(_review_lines(plan))
    assert "a new project" in lines
    assert "an existing folder" not in lines


def test_existing_folder_without_back_is_still_adopted(tmp_path) -> None:
    app, _spy = make_app()
    existing = _existing_folder(tmp_path)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _to_create_folder_prompt(pilot)
            await _submit_folder(pilot, str(existing))

    asyncio.run(scenario())

    assert app.result.project_mode == onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
    plan = _plan(app)
    assert "project-onboard-local-checkout" in _actions(plan)
    assert "project-create-checkout" not in _actions(plan)
    assert "an existing folder" in " ".join(_review_lines(plan))
