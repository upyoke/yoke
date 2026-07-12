"""Live-wizard coverage for fail-fast inline input validation.

Each free-text step rejects invalid input inline — it shows an error in the
``.onboard-input-error`` slot and stays on the same step — and only advances once
a valid value is entered. These drive the real ``OnboardWizardApp`` through the
pilot and read the live DOM, so they prove the gate fires before Apply (not just
that the pure validators return a string).
"""

from __future__ import annotations

import asyncio
import threading

import pytest

pytest.importorskip("textual")

from textual.widgets import Input, Static  # noqa: E402

from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_flow  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config import project_git_probe  # noqa: E402
from yoke_cli.config import project_git_transport  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
    type_text,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


@pytest.fixture(autouse=True)
def _stub_owners(monkeypatch):
    monkeypatch.setattr(
        onboard_wizard_flow, "fetch_repo_owners",
        lambda api_url, token: [github_owner()],
    )


def github_owner():
    from yoke_cli.config import github_publish

    return github_publish.RepoOwner("octocat", "user")


def _title(app) -> str:
    return next(
        str(w.render()) for w in app.query(".onboard-title").results(Static)
    )


def _error_text(app) -> str:
    return " ".join(
        str(w.render()) for w in app.query(".onboard-input-error").results(Static)
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
    await pilot.press("down")   # machine github: Skip for now
    await pilot.press("enter")


# ── clone URL reachability gate ──────────────────────────────────────────


def test_unreachable_clone_url_shows_recovery_then_retry_advances(
    monkeypatch,
) -> None:
    app, _spy = make_app()
    # The first probe says unreachable; flip to reachable for the retry.
    state = {"reachable": False}
    monkeypatch.setattr(
        project_git_transport,
        "remote_probe",
        lambda url, token=None, github_web_url=None: project_git_probe.GitRemoteProbe(
            state["reachable"],
            default_branch="main" if state["reachable"] else None,
            failure_kind=(
                None if state["reachable"] else project_git_probe.FAILURE_OTHER
            ),
        ),
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await type_text(pilot, "https://github.com/acme/missing.git")
            await pilot.press("enter")  # submit -> checking -> recovery
            await app.workers.wait_for_complete()
            await pilot.pause()
            # The network probe now runs after a visible checking screen, then
            # lands on a recovery screen instead of blocking the input render.
            assert not _has_input(app)
            assert "couldn't reach that repo" in _body_text(app).lower()
            assert app.result.project_remote_url is None
            # Now the repo is reachable; the same URL advances to the folder step.
            state["reachable"] = True
            await pilot.press("down")  # Change URL -> Try again
            await pilot.press("enter")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.result.project_remote_url == (
                "https://github.com/acme/missing.git"
            )
            assert _title(app) == "Where should Yoke clone it?"

    asyncio.run(scenario())


def test_clone_url_probe_paints_checking_before_it_finishes(monkeypatch) -> None:
    app, _spy = make_app()
    started = threading.Event()
    release = threading.Event()

    def _probe(url, token=None, *, github_web_url=None):
        started.set()
        assert release.wait(5), "test did not release clone URL probe"
        return project_git_probe.GitRemoteProbe(True, default_branch="main")

    monkeypatch.setattr(project_git_transport, "remote_probe", _probe)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await type_text(pilot, "https://github.com/acme/widgets.git")
            await pilot.press("enter")
            for _ in range(20):
                await pilot.pause()
                if started.is_set():
                    break
            assert started.is_set()
            assert _title(app) == "Checking source repo."
            assert "Checking..." in _body_text(app)
            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert _title(app) == "Where should Yoke clone it?"

    asyncio.run(scenario())


def test_reachable_clone_url_caches_branch_without_a_second_probe(
    monkeypatch,
) -> None:
    app, _spy = make_app()
    calls = {"probe": 0}

    def _probe(url, token=None, *, github_web_url=None):
        calls["probe"] += 1
        return project_git_probe.GitRemoteProbe(True, default_branch="trunk")

    monkeypatch.setattr(project_git_transport, "remote_probe", _probe)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_CLONE_REMOTE)
            await type_text(pilot, "https://github.com/acme/widgets.git")
            await pilot.press("enter")  # checking probe runs once -> advance
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.pause()

    asyncio.run(scenario())

    # The branch and reachability came from one structured checking probe and
    # were cached for _after_remote — exactly one ls-remote --symref ran.
    assert app.result.project_source_default_branch == "trunk"
    assert calls["probe"] == 1


# ── slug format gate ─────────────────────────────────────────────────────


def test_empty_slug_blocks_inline_after_clearing_default() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
            await type_text(pilot, "/home/code/widget")
            await pilot.press("enter")
            await pilot.pause()
            assert _title(app) == "Name your project."
            field = app.query_one("#onboard-input", Input)
            assert field.value == "widget"
            field.value = ""
            await pilot.press("enter")
            await pilot.pause()
            assert _title(app) == "Name your project."
            assert "short project id" in _error_text(app).lower()
            await type_text(pilot, "widget")
            await pilot.press("enter")
            await pilot.pause()
            assert app.result.project_slug == "widget"
            assert _title(app) == "Give it a friendly name."

    asyncio.run(scenario())


def test_invalid_slug_blocks_inline_then_a_valid_one_advances() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
            await type_text(pilot, "/home/code/widget")  # folder (stubbed-valid)
            await pilot.press("enter")
            await pilot.pause()
            # Slug step: an uppercase/space slug is rejected inline.
            assert _title(app) == "Name your project."
            await type_text(pilot, "Bad Slug")
            await pilot.press("enter")
            await pilot.pause()
            assert _title(app) == "Name your project."  # did not advance
            assert "lowercase" in _error_text(app).lower()
            # Clear and enter a valid slug -> advances to the friendly-name step.
            field = app.query_one("#onboard-input", Input)
            field.value = ""
            await type_text(pilot, "good-slug")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            assert app.result.project_slug == "good-slug"
            assert _title(app) == "Give it a friendly name."

    asyncio.run(scenario())


def test_very_long_slug_blocks_inline() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
            await type_text(pilot, "/home/code/widget")
            await pilot.press("enter")
            await pilot.pause()
            assert _title(app) == "Name your project."
            field = app.query_one("#onboard-input", Input)
            field.value = ""
            await type_text(pilot, "a" * 70)
            await pilot.press("enter")
            await pilot.pause()
            assert _title(app) == "Name your project."
            assert "63 characters" in _error_text(app)

    asyncio.run(scenario())


# ── display-name required gate ───────────────────────────────────────────


def test_empty_display_name_blocks_inline_after_clearing_default() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
            await type_text(pilot, "/home/code/widget")
            await pilot.press("enter")
            await pilot.press("enter")  # accept slug placeholder
            await pilot.pause()
            assert _title(app) == "Give it a friendly name."
            field = app.query_one("#onboard-input", Input)
            assert field.value == "widget"
            field.value = ""
            await pilot.press("enter")
            await pilot.pause()
            assert _title(app) == "Give it a friendly name."
            assert "display name" in _error_text(app).lower()
            await type_text(pilot, "Widget")
            await pilot.press("enter")
            await pilot.pause()
            assert app.result.project_name == "Widget"
            assert _title(app) == "Also publish to GitHub?"

    asyncio.run(scenario())


# ── prefix format gate ───────────────────────────────────────────────────


def test_invalid_prefix_blocks_inline() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
            await type_text(pilot, "/home/code/widget")
            await pilot.press("enter")
            await pilot.press("enter")  # slug placeholder
            await pilot.press("enter")  # name placeholder
            await pilot.press("down")   # publish: No
            await pilot.press("enter")
            await pilot.press("enter")  # default branch main (create/local keeps it)
            await pilot.pause()
            # Prefix step: a too-long / hyphenated prefix is rejected inline.
            assert _title(app) == "Pick the issue ID prefix."
            await type_text(pilot, "TOOLONG")
            await pilot.press("enter")
            await pilot.pause()
            assert _title(app) == "Pick the issue ID prefix."
            assert _error_text(app).strip()  # an error is shown

    asyncio.run(scenario())


# ── branch format gate (create-new keeps the branch prompt) ──────────────


def test_invalid_branch_blocks_inline() -> None:
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _skip_machine_github(pilot)
            await _pick_mode(pilot, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
            await type_text(pilot, "/home/code/widget")
            await pilot.press("enter")
            await pilot.press("enter")  # slug
            await pilot.press("enter")  # name
            await pilot.press("down")   # publish: No
            await pilot.press("enter")
            await pilot.pause()
            assert _title(app) == "Pick the default branch."
            await type_text(pilot, "bad branch")  # space -> invalid
            await pilot.press("enter")
            await pilot.pause()
            assert _title(app) == "Pick the default branch."  # blocked
            assert _error_text(app).strip()

    asyncio.run(scenario())
