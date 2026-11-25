"""Verify which screen receives keys typed while a setup check runs."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("textual")

from textual.widgets import Input  # noqa: E402
from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_flow_project_git as project_git  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
    type_text,
)
from runtime.api.cli.onboard_wizard_view_test_support import wait_for_view  # noqa: E402

if TYPE_CHECKING:
    from textual.pilot import Pilot


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_path_doctor(monkeypatch)


async def _start_create_project(pilot: Pilot) -> None:
    await advance_past_path(pilot)
    await pilot.press("down", "enter")  # machine GitHub: Skip for now
    create_index = next(
        i
        for i, row in enumerate(steps.MODE_ROWS)
        if row.value == onboard_project.PROJECT_MODE_CREATE_REPO
    )
    await pilot.press(*(["down"] * create_index), "enter")
    await wait_for_view(pilot, "check.onboard-project-git", checking=True)


def _wait_for_release(gate: threading.Event) -> None:
    assert gate.wait(timeout=30), "test did not release the setup check"


@pytest.mark.parametrize("early_text", ["~", "~t"])
def test_typing_during_check_reaches_project_folder(
    monkeypatch: pytest.MonkeyPatch, early_text: str
) -> None:
    app, _spy = make_app()
    gate = threading.Event()
    monkeypatch.setattr(
        project_git.project_git_prerequisite,
        "require_git_available",
        lambda: _wait_for_release(gate),
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            try:
                await _start_create_project(pilot)
                assert app._checking
                await type_text(pilot, early_text)
            finally:
                gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            await type_text(pilot, "~test"[len(early_text) :])
            field = app.query_one("#onboard-input", Input)
            assert app.focused is field
            assert field.value == "~test"

    asyncio.run(scenario())


def test_typing_during_check_is_discarded_when_git_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _spy = make_app()
    gate = threading.Event()

    def missing_git() -> None:
        _wait_for_release(gate)
        raise project_git.project_git_prerequisite.MissingGitError("git missing")

    monkeypatch.setattr(
        project_git.project_git_prerequisite, "require_git_available", missing_git
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            try:
                await _start_create_project(pilot)
                await type_text(pilot, "~x")
            finally:
                gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            await wait_for_view(pilot, "project.project_git_missing")
            assert not app.query(Input)

            monkeypatch.setattr(
                project_git.project_git_prerequisite,
                "require_git_available",
                lambda: None,
            )
            choices = app._history[-1].prompt.choices
            retry_index = next(
                i for i, row in enumerate(choices) if row.value == "retry"
            )
            await pilot.press(*(["down"] * retry_index), "enter")
            await wait_for_view(pilot, "project.folder", "#onboard-input")
            assert app.query_one("#onboard-input", Input).value == ""

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [False, True], ids=["success", "escape"])
def test_typing_during_check_routes_text_only_on_success(cancel: bool) -> None:
    app, _spy = make_app()
    gate = threading.Event()

    def show_input() -> None:
        app._goto_input(
            "test.answer",
            "Project",
            "Enter an answer.",
            "",
            placeholder="",
            on_done=lambda _value: None,
        )

    def unexpected_error(error: BaseException) -> None:
        raise AssertionError("setup check raised unexpectedly") from error

    async def scenario() -> None:
        async with app.run_test() as pilot:
            try:
                app._run_checking(
                    step="Project",
                    title="Checking.",
                    message="Waiting for the test.",
                    work=lambda: _wait_for_release(gate),
                    on_success=lambda _result: show_input(),
                    on_error=unexpected_error,
                    on_cancel=show_input,
                )
                await wait_for_view(pilot, "check.onboard-check", checking=True)
                await type_text(pilot, "xy")
                if cancel:
                    await pilot.press("escape")
                    assert not app._checking
            finally:
                gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            field = app.query_one("#onboard-input", Input)
            assert app.focused is field
            assert field.value == ("" if cancel else "xy")

    asyncio.run(scenario())
