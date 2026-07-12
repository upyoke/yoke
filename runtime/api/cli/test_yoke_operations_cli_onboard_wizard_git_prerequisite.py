"""Live-wizard coverage for the project git prerequisite gate."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Input, Static  # noqa: E402

from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config import project_git_install_advice  # noqa: E402
from yoke_cli.config import project_git_prerequisite  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
    type_text,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def _title(app) -> str:
    return next(
        str(w.render()) for w in app.query(".onboard-title").results(Static)
    )


def _body_text(app) -> str:
    return " ".join(
        str(w.render()) for w in app.query("#onboard-body Static").results(Static)
    )


def _has_input(app) -> bool:
    return bool(list(app.query("#onboard-body Input").results(Input)))


async def _pick_mode(pilot, value: str) -> None:
    index = next(i for i, r in enumerate(steps.MODE_ROWS) if r.value == value)
    for _ in range(index):
        await pilot.press("down")
    await pilot.press("enter")


async def _skip_machine_github(pilot) -> None:
    await advance_past_path(pilot)
    await pilot.press("down")
    await pilot.press("enter")


def _git_missing_dnf_available(name: str) -> str | None:
    if name == "git":
        return None
    if name in {"dnf", "sudo"}:
        return f"/usr/bin/{name}"
    return None


def _force_linux(monkeypatch) -> None:
    """Pin the git-prerequisite platform to Linux so the dnf package-manager
    assertions below are deterministic on any host (these tests exercise the
    Linux install UX; the macOS path is covered by its own pinned test). The
    wizard calls install_advice()/git_available() with no platform_name, so
    without this they resolve the host's real ``sys.platform`` and a macOS dev
    box gets Apple-CLT advice instead of dnf."""
    real_advice = project_git_install_advice.install_advice
    monkeypatch.setattr(
        project_git_install_advice,
        "install_advice",
        lambda **kw: real_advice(**{**kw, "platform_name": "linux"}),
    )
    real_available = project_git_prerequisite.git_available
    monkeypatch.setattr(
        project_git_prerequisite,
        "git_available",
        lambda **kw: real_available(**{**kw, "platform_name": "linux"}),
    )


@pytest.mark.parametrize(
    "mode",
    [
        onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        onboard_project.PROJECT_MODE_CLONE_REMOTE,
        onboard_project.PROJECT_MODE_CREATE_REPO,
        onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN,
    ],
)
def test_project_modes_fail_fast_when_git_is_missing(monkeypatch, mode: str) -> None:
    app, _spy = make_app()
    _force_linux(monkeypatch)
    monkeypatch.setattr(
        project_git_prerequisite.shutil, "which", _git_missing_dnf_available,
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, mode)
            await app.workers.wait_for_complete()
            await pilot.pause()
            body = _body_text(app).lower()
            assert not _has_input(app)
            assert "git is required" in body
            assert "install git" in body
            assert "sudo dnf install -y git" in body
            assert app.result.project_mode == mode

    asyncio.run(scenario())


def test_missing_git_retry_continues_after_install(monkeypatch) -> None:
    app, _spy = make_app()
    _force_linux(monkeypatch)
    state = {"installed": False}

    def _which(name: str) -> str | None:
        if name == "git":
            return "/usr/bin/git" if state["installed"] else None
        if name in {"dnf", "sudo"}:
            return f"/usr/bin/{name}"
        return None

    monkeypatch.setattr(project_git_prerequisite.shutil, "which", _which)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "sudo dnf install -y git" in _body_text(app)
            state["installed"] = True
            await pilot.press("down")  # Install Git -> Try again
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert _title(app) == "Clone a project from GitHub."

    asyncio.run(scenario())


def test_missing_git_install_action_runs_helper_then_continues(monkeypatch) -> None:
    app, _spy = make_app()
    _force_linux(monkeypatch)
    state = {"installed": False, "install_calls": 0}

    def _which(name: str) -> str | None:
        if name == "git":
            return "/usr/bin/git" if state["installed"] else None
        if name in {"dnf", "sudo"}:
            return f"/usr/bin/{name}"
        return None

    def _install_git() -> None:
        state["install_calls"] += 1
        state["installed"] = True

    monkeypatch.setattr(project_git_prerequisite.shutil, "which", _which)
    monkeypatch.setattr(project_git_prerequisite, "install_git", _install_git)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            project_depth = len(app._history)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "install git" in _body_text(app).lower()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert state["install_calls"] == 1
            assert _title(app) == "Clone a project from GitHub."
            assert len(app._history) == project_depth + 1
            await pilot.press("escape")
            await pilot.pause()
            assert _title(app) == "Set up a project."
            assert len(app._history) == project_depth

    asyncio.run(scenario())


def test_missing_git_manual_only_does_not_offer_install(monkeypatch) -> None:
    app, _spy = make_app()
    _force_linux(monkeypatch)

    def _which(name: str) -> str | None:
        if name == "dnf":
            return "/usr/bin/dnf"
        return None

    monkeypatch.setattr(project_git_prerequisite.shutil, "which", _which)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await app.workers.wait_for_complete()
            await pilot.pause()
            body = _body_text(app).lower()
            assert "run this manually" in body
            assert "dnf install -y git" in body
            assert "install git" not in body

    asyncio.run(scenario())


def test_missing_git_macos_handoff_keeps_wizard_open(monkeypatch) -> None:
    app, _spy = make_app()
    state = {"finalize_calls": 0}
    advice = project_git_prerequisite.GitInstallAdvice(
        "macOS",
        "xcode-select --install",
        "This opens Apple's Command Line Tools installer.",
        (("/usr/bin/xcode-select", "--install"),),
        requires_user_completion=True,
    )

    monkeypatch.setattr(project_git_prerequisite.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        project_git_prerequisite,
        "install_advice",
        lambda **_kwargs: advice,
    )
    monkeypatch.setattr(project_git_prerequisite, "install_git", lambda: advice)
    monkeypatch.setattr(
        project_git_prerequisite,
        "finalize_git_install",
        lambda: state.__setitem__(
            "finalize_calls",
            state["finalize_calls"] + 1,
        ),
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "install apple tools" in _body_text(app).lower()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            body = _body_text(app).lower()
            assert "command line tools installer should be open" in body
            assert "check again" in body
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert state["finalize_calls"] == 1

    asyncio.run(scenario())


def test_clone_url_probe_missing_git_is_not_repo_unreachable(monkeypatch) -> None:
    app, _spy = make_app()
    _force_linux(monkeypatch)
    state = {"git_available": True}

    def _which(name: str) -> str | None:
        if name == "git":
            return "/usr/bin/git" if state["git_available"] else None
        if name in {"dnf", "sudo"}:
            return f"/usr/bin/{name}"
        return None

    monkeypatch.setattr(project_git_prerequisite.shutil, "which", _which)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert _title(app) == "Clone a project from GitHub."
            state["git_available"] = False
            await type_text(pilot, "https://github.com/antirez/kilo.git")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            body = _body_text(app).lower()
            assert "git is required" in body
            assert "install git" in body
            assert "couldn't reach that repo" not in body

    asyncio.run(scenario())


def test_project_git_retry_and_back_do_not_accumulate_recovery_views(
    monkeypatch,
) -> None:
    app, _spy = make_app()
    _force_linux(monkeypatch)
    monkeypatch.setattr(
        project_git_prerequisite.shutil, "which", _git_missing_dnf_available,
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            project_depth = len(app._history)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await app.workers.wait_for_complete()
            await pilot.pause()
            error_depth = len(app._history)
            assert error_depth == project_depth + 1

            for _ in range(2):
                await pilot.press("down")  # Install Git -> Try again
                await pilot.press("enter")
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert "git is required" in _body_text(app).lower()
                assert len(app._history) == error_depth

            await pilot.press("down")  # Install Git -> Try again
            await pilot.press("down")  # Try again -> Back
            await pilot.press("enter")
            await pilot.pause()
            assert _title(app) == "Set up a project."
            assert "git is required" not in _body_text(app).lower()
            assert len(app._history) == project_depth

    asyncio.run(scenario())
