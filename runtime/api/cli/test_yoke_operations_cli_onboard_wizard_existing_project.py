"""Existing-project detection flows for the full-screen onboard wizard."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess

import pytest

pytest.importorskip("textual")

from textual.widgets import Static  # noqa: E402

from yoke_cli.config import existing_project_lookup  # noqa: E402
from yoke_cli.config.onboard_wizard import WizardDefaults  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    complete_board_art,
    make_app,
    stub_path_doctor,
    type_text,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def _configure_origin(checkout: Path, repo: str) -> None:
    subprocess.run(
        ["git", "init", "--initial-branch", "main"],
        cwd=checkout,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        [
            "git",
            "-c", "user.name=Yoke Test",
            "-c", "user.email=yoke-test@example.invalid",
            "commit", "--allow-empty", "-m", "fixture",
        ],
        cwd=checkout,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        [
            "git", "remote", "add", "origin",
            f"https://github.com/{repo}.git",
        ],
        cwd=checkout,
        check=True,
    )


def test_local_checkout_manifest_project_id_skips_project_setup(
    tmp_path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "buzz"
    (checkout / ".yoke").mkdir(parents=True)
    (checkout / ".yoke" / "install-manifest.json").write_text(
        '{"manifest_schema": 1, "project_id": 37}\n',
        encoding="utf-8",
    )
    _configure_origin(checkout, "example-org/buzz")
    monkeypatch.setattr(
        existing_project_lookup,
        "find_by_project_id",
        lambda **_: existing_project_lookup.ExistingProject(
            id=37,
            slug="buzz",
            name="Buzz",
            github_repo="example-org/buzz",
            default_branch="main",
            public_item_prefix="BUZZ",
        ),
    )
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")  # machine github: Skip for now
            await pilot.press("enter")
            await pilot.press("enter")  # project: existing folder
            await type_text(pilot, str(checkout))
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            body = _body_text(app)
            assert "Existing Yoke project found." in body
            assert (
                "Local project metadata matched a Yoke core database project." in body
            )
            assert (
                "Local machine: found project id 37 in .yoke/install-manifest.json."
                in body
            )
            assert "Yoke core database: verified project id 37." in body
            await pilot.press("enter")  # continue -> board art
            await complete_board_art(pilot)
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["existing_project_id"] == 37
    assert applied["project_slug"] == "buzz"
    assert applied["project_name"] == "Buzz"
    assert len(app.result.board_art_variants) == 1


def test_stored_checkout_project_id_shows_confirmation_picker(
    tmp_path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "buzz"
    checkout.mkdir()
    _configure_origin(checkout, "example-org/buzz")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"projects": {str(checkout): {"project_id": 37}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        existing_project_lookup,
        "find_by_project_id",
        lambda **_: existing_project_lookup.ExistingProject(
            id=37,
            slug="buzz",
            name="Buzz",
            github_repo="example-org/buzz",
            default_branch="main",
            public_item_prefix="BUZZ",
        ),
    )
    app, spy = make_app(
        WizardDefaults(
            config_path=str(config),
            env_name="prod",
            api_url="https://api.test",
            token="actor-token",
        )
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")  # machine github: Skip for now
            await pilot.press("enter")
            await pilot.pause()
            assert "Use an existing project mapping?" in _body_text(app)
            assert str(checkout) in _body_text(app)
            await pilot.press("enter")  # stored mapping: reuse checkout
            await app.workers.wait_for_complete()
            await pilot.pause()
            body = _body_text(app)
            assert "Existing Yoke project found." in body
            assert "Checkout:" in body
            assert (
                "Local project metadata matched a Yoke core database project." in body
            )
            assert "Local machine: found project id 37 in machine config." in body
            assert "Yoke core database: verified project id 37." in body
            assert str(checkout) in body
            assert "~/code/my-project" not in body
            await pilot.press("enter")  # continue -> board art
            await complete_board_art(pilot)
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["project_checkout"] == str(checkout)
    assert applied["existing_project_id"] == 37
    assert applied["project_slug"] == "buzz"
    assert applied["project_name"] == "Buzz"
    assert len(app.result.board_art_variants) == 1


def test_existing_project_with_board_art_skips_art_flow(
    tmp_path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "buzz"
    (checkout / ".yoke").mkdir(parents=True)
    (checkout / ".yoke" / "install-manifest.json").write_text(
        '{"manifest_schema": 1, "project_id": 37}\n',
        encoding="utf-8",
    )
    (checkout / ".yoke" / "board-art").write_text("# art\n", encoding="utf-8")
    _configure_origin(checkout, "example-org/buzz")
    monkeypatch.setattr(
        existing_project_lookup,
        "find_by_project_id",
        lambda **_: existing_project_lookup.ExistingProject(
            id=37,
            slug="buzz",
            name="Buzz",
            github_repo="example-org/buzz",
            default_branch="main",
            public_item_prefix="BUZZ",
        ),
    )
    app, spy = make_app(
        WizardDefaults(
            config_path=str(tmp_path / "config.json"),
            env_name="prod",
            api_url="https://api.test",
            token="actor-token",
        )
    )

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")  # machine github: Skip for now
            await pilot.press("enter")
            await pilot.press("enter")  # project: existing folder
            await type_text(pilot, str(checkout))
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "Existing Yoke project found." in _body_text(app)
            await pilot.press("enter")  # continue -> Finish
            await pilot.press("enter")  # finish: apply
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["existing_project_id"] == 37
    assert app.result.board_art_variants == []


def _body_text(app) -> str:
    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )
