"""A folder linked to another install's project offers "Unlink and set up fresh"."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from textual.widgets import Static  # noqa: E402

from yoke_cli.config import existing_project_lookup  # noqa: E402
from yoke_cli.config import onboard_existing_project  # noqa: E402

from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    stub_path_doctor,
    type_text,
)


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


def _linked_checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "externalwebapp"
    (checkout / ".yoke").mkdir(parents=True)
    (checkout / ".yoke" / "install-manifest.json").write_text(
        '{"manifest_schema": 1, "project_id": 1}\n', encoding="utf-8"
    )
    for args in (
        ["init", "--initial-branch", "main"],
        [
            "-c",
            "user.name=T",
            "-c",
            "user.email=t@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        [
            "remote",
            "add",
            "origin",
            "https://github.com/example-org/externalwebapp.git",
        ],
    ):
        subprocess.run(["git", *args], cwd=checkout, check=True, capture_output=True)
    return checkout


def _body_text(app) -> str:
    return " ".join(
        str(widget.render())
        for widget in app.query("#onboard-body Static").results(Static)
    )


def test_unlink_continues_setup_without_the_old_project(tmp_path, monkeypatch):
    checkout = _linked_checkout(tmp_path)
    by_id: list[int] = []
    by_repo: list[str] = []

    def missing(**kwargs):
        by_id.append(kwargs["project_id"])
        raise existing_project_lookup.ExistingProjectReferenceError(
            "project '1' not found"
        )

    def no_repo_match(**kwargs):
        by_repo.append(kwargs["github_repo"])
        return None

    monkeypatch.setattr(existing_project_lookup, "find_by_project_id", missing)
    monkeypatch.setattr(existing_project_lookup, "find_by_github_repo", no_repo_match)
    app, _spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("down")  # machine github: Skip for now
            await pilot.press("enter")
            await pilot.press("down", "enter")  # project: existing folder
            await type_text(pilot, str(checkout))
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            body = _body_text(app)
            assert "linked to a project from a different Yoke install" in body
            assert "links this folder to project 1" in body
            assert "Unlink and set up fresh" in body
            assert "API token" not in body
            await pilot.press("enter")  # Unlink and set up fresh
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "different Yoke install" not in _body_text(app)

    asyncio.run(scenario())

    assert by_id == [1]
    assert by_repo == ["https://github.com/example-org/externalwebapp.git"]
    assert app.result.existing_project_id is None
    assert (checkout / ".yoke" / "install-manifest.json").is_file()


def test_access_denied_link_names_the_account_not_a_token():
    local_ref = existing_project_lookup.LocalProjectReference(1, "machine config")
    title, lines = onboard_existing_project.stale_link_copy(
        SimpleNamespace(destination="hosted"),
        existing_project_lookup.ExistingProjectAccessError("denied"),
        local_ref,
    )
    assert title == "This folder is linked to a project you can't use."
    assert "machine config links this folder to project 1" in lines[0]
    assert all("token" not in line for line in [title, *lines])


@pytest.mark.parametrize("local_destination", [False, True])
def test_lookup_hint_never_asks_for_an_api_token(local_destination):
    hint = onboard_existing_project.lookup_error_hint(
        local_destination=local_destination
    )
    assert "token" not in hint.lower()
