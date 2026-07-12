"""Bounded-history coverage for clone-source Git recovery screens."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Static  # noqa: E402

from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config import project_git_install_advice  # noqa: E402
from yoke_cli.config import project_git_probe  # noqa: E402
from yoke_cli.config import project_git_prerequisite  # noqa: E402
from yoke_cli.config import project_git_transport  # noqa: E402

from runtime.api.cli.onboard_wizard_github_app_test_support import (  # noqa: E402
    connect_github_app,
)
from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
    type_text,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def _force_linux(monkeypatch) -> None:
    real_advice = project_git_install_advice.install_advice
    monkeypatch.setattr(
        project_git_install_advice,
        "install_advice",
        lambda **kwargs: real_advice(**{**kwargs, "platform_name": "linux"}),
    )
    real_available = project_git_prerequisite.git_available
    monkeypatch.setattr(
        project_git_prerequisite,
        "git_available",
        lambda **kwargs: real_available(
            **{**kwargs, "platform_name": "linux"}
        ),
    )


def _available_git(name: str) -> str | None:
    if name == "git":
        return "/usr/bin/git"
    if name in {"dnf", "sudo"}:
        return f"/usr/bin/{name}"
    return None


def _stub_unreachable_remote(monkeypatch) -> None:
    monkeypatch.setattr(
        project_git_transport,
        "remote_probe",
        lambda *_args, **_kwargs: project_git_probe.GitRemoteProbe(
            False,
            default_branch=None,
            failure_kind=project_git_probe.FAILURE_OTHER,
        ),
    )


def _title(app) -> str:
    return next(
        str(widget.render())
        for widget in app.query(".onboard-title").results(Static)
    )


def _body_text(app) -> str:
    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


async def _pick_clone_mode(pilot) -> None:
    index = next(
        index
        for index, row in enumerate(steps.MODE_ROWS)
        if row.value == onboard_project.PROJECT_MODE_CLONE_REMOTE
    )
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")


async def _skip_machine_github(pilot) -> None:
    await advance_past_path(pilot)
    await pilot.press("down")
    await pilot.press("enter")


def test_clone_remote_retry_edit_and_back_keep_history_bounded(
    monkeypatch,
) -> None:
    app, _spy = make_app()
    _force_linux(monkeypatch)
    monkeypatch.setattr(
        project_git_prerequisite.shutil, "which", _available_git,
    )
    _stub_unreachable_remote(monkeypatch)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            project_depth = len(app._history)
            await _pick_clone_mode(pilot)
            await app.workers.wait_for_complete()
            await pilot.pause()
            await type_text(pilot, "https://github.com/acme/widgets.git")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            error_depth = len(app._history)
            assert "couldn't reach that repo" in _body_text(app).lower()

            await pilot.press("down")  # Change URL -> Try again
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "couldn't reach that repo" in _body_text(app).lower()
            assert len(app._history) == error_depth

            await pilot.press("enter")  # Change URL
            await pilot.pause()
            assert _title(app) == "Clone a project from GitHub."
            assert len(app._history) == error_depth - 1

            await type_text(pilot, "https://github.com/acme/other.git")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert len(app._history) == error_depth
            await pilot.press("down")  # Change URL -> Try again
            await pilot.press("down")  # Try again -> Back
            await pilot.press("enter")
            await pilot.pause()
            assert _title(app) == "Set up a project."
            assert "couldn't reach that repo" not in _body_text(app).lower()
            assert len(app._history) == project_depth

    asyncio.run(scenario())


def test_clone_git_install_replaces_missing_git_recovery_view(
    monkeypatch,
) -> None:
    app, _spy = make_app()
    _force_linux(monkeypatch)
    state = {"installed": True, "install_calls": 0}

    def _which(name: str) -> str | None:
        if name == "git":
            return "/usr/bin/git" if state["installed"] else None
        return _available_git(name)

    def _install_git() -> None:
        state["install_calls"] += 1
        state["installed"] = True

    def _remote_probe(*_args, **_kwargs):
        project_git_prerequisite.require_git_available()
        return project_git_probe.GitRemoteProbe(
            True,
            default_branch="main",
            failure_kind=None,
        )

    monkeypatch.setattr(project_git_prerequisite.shutil, "which", _which)
    monkeypatch.setattr(project_git_prerequisite, "install_git", _install_git)
    monkeypatch.setattr(project_git_transport, "remote_probe", _remote_probe)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            project_depth = len(app._history)
            await _pick_clone_mode(pilot)
            await app.workers.wait_for_complete()
            await pilot.pause()
            state["installed"] = False
            await type_text(pilot, "https://github.com/acme/widgets.git")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "git is required" in _body_text(app).lower()

            await pilot.press("enter")  # Install Git
            await app.workers.wait_for_complete()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert state["install_calls"] == 1
            assert _title(app) == "Where should Yoke clone it?"
            assert len(app._history) == project_depth + 2
            await pilot.press("escape")
            await pilot.pause()
            assert _title(app) == "Clone a project from GitHub."
            assert "git is required" not in _body_text(app).lower()

    asyncio.run(scenario())


def test_connected_clone_remote_back_returns_to_visibility_without_stale_error(
    monkeypatch,
) -> None:
    app, _spy = make_app()
    _force_linux(monkeypatch)
    monkeypatch.setattr(
        project_git_prerequisite.shutil, "which", _available_git,
    )
    _stub_unreachable_remote(monkeypatch)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await connect_github_app(app, pilot)
            project_depth = len(app._history)
            await _pick_clone_mode(pilot)
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press("enter")  # Public -> URL input
            await type_text(pilot, "https://github.com/acme/widgets.git")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "couldn't reach that repo" in _body_text(app).lower()

            await pilot.press("down")  # Change URL -> Try again
            await pilot.press("down")  # Try again -> Back
            await pilot.press("enter")
            await pilot.pause()
            assert _title(app) == "Is the repo public or private?"
            assert "couldn't reach that repo" not in _body_text(app).lower()
            assert len(app._history) == project_depth + 1
            await pilot.press("escape")
            await pilot.pause()
            assert _title(app) == "Set up a project."
            assert len(app._history) == project_depth

    asyncio.run(scenario())
