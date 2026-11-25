"""GitHub binding for detected origins in existing project checkouts."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("textual")

from yoke_contracts import github_app_installation_permissions  # noqa: E402
from runtime.api.cli.onboard_wizard_test_helpers import (  # noqa: E402
    advance_past_path,
    make_app,
    skip_hosting,
    stub_path_doctor,
    submit_public_item_prefix,
    type_text,
)
from runtime.api.cli.onboard_wizard_github_navigation_safety_test_support import (_body_text)
from runtime.api.cli.yoke_operations_cli_onboard_wizard_existing_project_test_support import (_configure_origin)
from yoke_cli.config import existing_project_lookup  # noqa: E402
from yoke_cli.config import github_machine  # noqa: E402
from yoke_contracts.machine_config import reader as machine_config  # noqa: E402
from yoke_cli.config import onboard_local_checkout_identity  # noqa: E402
from yoke_cli.config import onboard_machine_github  # noqa: E402
from yoke_cli.config import project_local_git  # noqa: E402
from runtime.api.cli.onboard_wizard_view_test_support import wait_for_view  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_path_doctor(monkeypatch):
    stub_path_doctor(monkeypatch)


@pytest.fixture(autouse=True)
def _live_repository_report(monkeypatch, _stub_path_doctor):
    stubbed_status = github_machine.status

    def status(**kwargs):
        config = machine_config.github_config(kwargs.get("config_path"))
        return {
            **stubbed_status(**kwargs),
            "identity": {"checked": True, "ok": True},
            "access": {
                "repo_listing_ok": True,
                "repositories": config.get("repositories", []),
                "installations": config.get("installations", []),
            },
        }

    monkeypatch.setattr(github_machine, "status", status)


def test_existing_backlog_project_can_bind_detected_checkout_origin(
    tmp_path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "legacy"
    (checkout / ".yoke").mkdir(parents=True)
    (checkout / ".yoke" / "install-manifest.json").write_text(
        '{"manifest_schema": 1, "project_id": 37}\n',
        encoding="utf-8",
    )
    _configure_origin(checkout, "example-org/legacy")
    monkeypatch.setattr(
        existing_project_lookup,
        "find_by_project_id",
        lambda **_: existing_project_lookup.ExistingProject(
            id=37,
            slug="legacy",
            name="Legacy",
            github_repo="",
            default_branch="main",
            public_item_prefix="LEG",
            github_sync_mode="disabled",
        ),
    )

    def detect_origin(result, value):
        assert Path(value).resolve() == checkout.resolve()
        local_ref = existing_project_lookup.find_local_project_reference(
            value, config_path=result.config_path,
        )
        assert local_ref is not None, value
        assert local_ref.project_id == 37
        result.project_github_repo = "example-org/legacy"
        result.project_source_default_branch = "main"
        return "https://github.com/example-org/legacy.git", "https://github.com"

    monkeypatch.setattr(
        onboard_local_checkout_identity,
        "inspect",
        detect_origin,
    )
    monkeypatch.setattr(
        machine_config,
        "github_config",
        lambda _path: {
            "installations": [
                {
                    "installation_id": 7,
                    "account_login": "example-org",
                    "repository_selection": "selected",
                    "permissions": dict(
                        github_app_installation_permissions.REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS
                    ),
                }
            ],
            "repositories": [
                {
                    "repository_id": 9,
                    "installation_id": 7,
                    "full_name": "example-org/legacy",
                }
            ],
        },
    )
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")  # connect GitHub
            await wait_for_view(pilot, "project.mode", "SelectionList")
            await pilot.press("down", "enter")  # existing folder
            await type_text(pilot, str(checkout))
            await pilot.press("enter")
            await wait_for_view(pilot, "project.existing_found", "SelectionList")
            assert "Existing project found: Legacy." in _body_text(app)
            await pilot.press("enter")  # continue to GitHub adoption
            await wait_for_view(pilot, "project.github", "SelectionList")
            assert "How should Yoke manage this project on GitHub?" in _body_text(app)
            await pilot.press("enter")  # use connected installation
            await wait_for_view(pilot, "hosting.provider", "SelectionList")
            assert "Connect your hosting provider?" in _body_text(app)
            assert [v.kind for v in app.result.board_art_variants] == [
                "ASCII",
                "Emoji",
                "Mixed",
            ]
            await skip_hosting(pilot)  # hosting: skip -> Finish
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["existing_project_id"] == 37
    assert applied["project_github_repo"] == "example-org/legacy"
    assert applied["project_github_adoption"] == "app-binding"
    assert applied["project_github_adoption_preserve"] is False
    assert applied["machine_github_choice"] == onboard_machine_github.CHOICE_CONNECT


def test_new_project_keeps_existing_origin_and_reaches_binding(
    tmp_path,
    monkeypatch,
) -> None:
    checkout = tmp_path / "new-project"
    checkout.mkdir()
    repository = "example-org/new-project"
    origin = f"https://github.com/{repository}.git"
    _configure_origin(checkout, repository)
    subprocess.run(
        ["git", "branch", "-m", "trunk"], cwd=checkout, check=True, capture_output=True
    )
    checkout_git = {
        ("rev-parse", "--is-inside-work-tree"): "true\n",
        ("rev-parse", "--show-toplevel"): f"{checkout}\n",
        ("config", "--local", "--get-all", "remote.origin.url"): f"{origin}\n",
        ("remote",): "origin\n",
    }
    real_git = project_local_git.run

    def read_checkout(root, *args):
        if root.resolve() != checkout.resolve():
            return real_git(root, *args)
        return subprocess.CompletedProcess(args, 0, stdout=checkout_git[args], stderr="")

    # This scenario takes the publish path, without choosing a clone outcome.
    def detect_origin(result, _value):
        result.project_github_repo = repository
        result.project_source_default_branch = "trunk"
        return origin, "https://github.com"

    monkeypatch.setattr(project_local_git, "run", read_checkout)
    monkeypatch.setattr(onboard_local_checkout_identity, "inspect", detect_origin)
    monkeypatch.setattr(
        machine_config,
        "github_config",
        lambda _path: {
            "installations": [
                {
                    "installation_id": 7,
                    "account_login": "example-org",
                    "repository_selection": "selected",
                    "permissions": dict(
                        github_app_installation_permissions.REQUIRED_GITHUB_APP_REPOSITORY_PERMISSION_LEVELS
                    ),
                }
            ],
            "repositories": [
                {
                    "repository_id": 9,
                    "installation_id": 7,
                    "full_name": "example-org/new-project",
                }
            ],
        },
    )
    app, spy = make_app()

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await advance_past_path(pilot)
            await pilot.press("enter")  # connect GitHub
            await wait_for_view(pilot, "project.mode", "SelectionList")
            await pilot.press("down", "enter")  # existing folder
            await type_text(pilot, str(checkout))
            await pilot.press("enter")
            await wait_for_view(pilot, "project.details", "#onboard-input-slug")
            await pilot.press("enter")  # accept slug
            await pilot.press("enter")  # accept name; keep remote auto-routes
            await submit_public_item_prefix(pilot)
            await wait_for_view(pilot, "project.github", "SelectionList")
            assert "How should Yoke manage this project on GitHub?" in _body_text(app)
            await pilot.press("enter")
            await wait_for_view(pilot, "hosting.provider", "SelectionList")
            assert "Connect your hosting provider?" in _body_text(app)
            assert [v.kind for v in app.result.board_art_variants] == [
                "ASCII",
                "Emoji",
                "Mixed",
            ]
            await skip_hosting(pilot)  # hosting: skip -> Finish
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(scenario())

    applied = spy.applied
    assert applied is not None
    assert applied["existing_project_id"] is None
    assert applied["project_keep_existing_remote"] is True
    assert applied["project_github_repo"] == "example-org/new-project"
    assert applied["project_default_branch"] == "trunk"
    assert applied["project_github_adoption"] == "app-binding"
    assert applied["project_github_adoption_preserve"] is False
    assert subprocess.check_output(
        ["git", "config", "--local", "--get", "remote.origin.url"],
        cwd=checkout,
        text=True,
    ).strip() == origin
